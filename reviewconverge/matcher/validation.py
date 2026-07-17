"""Matcher validation — the sub-study reviewers attack first (PLANS §4.2).

The paper measuring hallucinated findings must not rest on a hallucinating
matcher, so the matcher ships with its own evidence:

- a **gold set** of labeled finding pairs (same/different),
- **precision/recall** of the matcher against those labels,
- **inter-rater agreement** (Cohen's κ) between two label sources,
- **self-agreement / flip rate** — run the matcher twice and count verdicts that
  change (the direct test of the determinism claim), and
- a **threshold sensitivity** sweep showing P/R is stable under perturbation.

The bootstrap gold set here is *derived from the frozen oracle*: paraphrases of
one seeded defect are same-issue positives (the oracle authored them as such),
and two distinct seeded defects are different-issue negatives — with
same-artifact defect pairs as the hard negatives. This gives an immediate,
$0, reproducible P/R read. Independent human + frontier-model second-opinion
labels (for κ against a non-oracle source) are layered on top next; this module
computes κ for whatever two label columns it is given.
"""

from __future__ import annotations

import itertools
import json
import random
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Optional

from ..schema import Location
from .cache import DecisionCache, finding_fingerprint
from .core import Judge, Matcher


@dataclass(frozen=True)
class GoldPair:
    """One labeled finding pair for matcher validation."""

    pair_id: str
    a_text: str
    b_text: str
    label: bool  # True = same issue
    source: str  # how the label was derived, e.g. "oracle:paraphrase", "oracle:cross-defect"
    a_unit: Optional[str] = None
    a_start: Optional[int] = None
    a_end: Optional[int] = None
    b_unit: Optional[str] = None
    b_start: Optional[int] = None
    b_end: Optional[int] = None

    def a_location(self) -> Optional[Location]:
        return Location(self.a_unit, self.a_start, self.a_end) if self.a_unit is not None else None

    def b_location(self) -> Optional[Location]:
        return Location(self.b_unit, self.b_start, self.b_end) if self.b_unit is not None else None


# -- gold-set construction ------------------------------------------------
def build_gold_from_corpus(items: Iterable, sample: Optional[int] = None, seed: int = 0) -> list[GoldPair]:
    """Derive labeled pairs from the frozen oracle.

    Positives: (description, paraphrase) and (paraphrase, paraphrase) of the same
    defect. Negatives: distinct-defect description pairs, hard negatives (same
    artifact) first, then a deterministic sample of cross-artifact easy negatives
    to roughly balance the classes.

    Args:
        items: loaded ``CorpusItem`` objects (each with ``.item_id`` and
            ``.defects``).
        sample: if set, deterministically stratified-downsample to about this
            many pairs (balanced same/different), for the human-labeling queue.
        seed: PRNG seed for reproducible sampling.
    """
    items = list(items)
    positives: list[GoldPair] = []
    hard_neg: list[GoldPair] = []
    easy_neg: list[GoldPair] = []

    def loc_fields(loc: Location) -> dict:
        return {"unit": loc.unit, "start": loc.start, "end": loc.end}

    # Positives — within a single defect.
    for it in items:
        for d in it.defects:
            variants = [d.description, *d.paraphrases]
            lf = loc_fields(d.location)
            for x, y in itertools.combinations(range(len(variants)), 2):
                positives.append(
                    GoldPair(
                        pair_id=f"{d.id}~pos~{x}-{y}",
                        a_text=variants[x],
                        b_text=variants[y],
                        label=True,
                        source="oracle:paraphrase",
                        a_unit=lf["unit"], a_start=lf["start"], a_end=lf["end"],
                        b_unit=lf["unit"], b_start=lf["start"], b_end=lf["end"],
                    )
                )

    # Hard negatives — distinct defects in the SAME artifact (share context).
    for it in items:
        for d1, d2 in itertools.combinations(it.defects, 2):
            hard_neg.append(
                GoldPair(
                    pair_id=f"{d1.id}~neg~{d2.id}",
                    a_text=d1.description,
                    b_text=d2.description,
                    label=False,
                    source="oracle:cross-defect-same-artifact",
                    a_unit=d1.location.unit, a_start=d1.location.start, a_end=d1.location.end,
                    b_unit=d2.location.unit, b_start=d2.location.start, b_end=d2.location.end,
                )
            )

    # Easy negatives — distinct defects across DIFFERENT artifacts (deterministic).
    rng = random.Random(seed)
    all_defects = [(it, d) for it in items for d in it.defects]
    n_easy = len(positives) - len(hard_neg)  # aim to balance classes
    tries = 0
    seen: set[tuple[str, str]] = set()
    while len(easy_neg) < max(0, n_easy) and tries < 50_000:
        tries += 1
        (i1, d1), (i2, d2) = rng.choice(all_defects), rng.choice(all_defects)
        if i1.id == i2.id:
            continue
        key = tuple(sorted((d1.id, d2.id)))
        if key in seen:
            continue
        seen.add(key)
        easy_neg.append(
            GoldPair(
                pair_id=f"{d1.id}~xneg~{d2.id}",
                a_text=d1.description,
                b_text=d2.description,
                label=False,
                source="oracle:cross-defect-cross-artifact",
                a_unit=d1.location.unit, a_start=d1.location.start, a_end=d1.location.end,
                b_unit=d2.location.unit, b_start=d2.location.start, b_end=d2.location.end,
            )
        )

    pairs = positives + hard_neg + easy_neg
    pairs.sort(key=lambda p: p.pair_id)
    if sample is not None and sample < len(pairs):
        pairs = _stratified_sample(pairs, sample, seed)
    return pairs


def _stratified_sample(pairs: list[GoldPair], n: int, seed: int) -> list[GoldPair]:
    """Deterministic balanced downsample preserving same/different proportions ~50/50."""
    rng = random.Random(seed)
    pos = [p for p in pairs if p.label]
    neg = [p for p in pairs if not p.label]
    rng.shuffle(pos)
    rng.shuffle(neg)
    half = n // 2
    out = pos[:half] + neg[: n - half]
    out.sort(key=lambda p: p.pair_id)
    return out


def write_gold_jsonl(pairs: list[GoldPair], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for p in pairs:
            fh.write(json.dumps(asdict(p), sort_keys=True) + "\n")


def load_gold_jsonl(path: Path) -> list[GoldPair]:
    out: list[GoldPair] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(GoldPair(**json.loads(line)))
    return out


# -- metrics --------------------------------------------------------------
@dataclass
class PRReport:
    n: int
    tp: int
    fp: int
    fn: int
    tn: int

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def accuracy(self) -> float:
        return (self.tp + self.tn) / self.n if self.n else 1.0

    def to_dict(self) -> dict:
        return {
            "n": self.n, "tp": self.tp, "fp": self.fp, "fn": self.fn, "tn": self.tn,
            "precision": round(self.precision, 4), "recall": round(self.recall, 4),
            "f1": round(self.f1, 4), "accuracy": round(self.accuracy, 4),
        }


def band_pairs(pairs: list[GoldPair], matcher: Optional[Matcher] = None) -> list[GoldPair]:
    """The pairs the deterministic pass leaves to the judge (``lexical-fallback``)."""
    det = matcher or Matcher(judge=None)
    return [
        p for p in pairs
        if det.decide_pair(p.a_text, p.a_location(), p.b_text, p.b_location(),
                           use_cache=False).method == "lexical-fallback"
    ]


def _decide(judge: Judge, p: GoldPair) -> tuple[bool, bool]:
    """Return ``(verdict, decided)`` — judges with a ``decide`` method report
    whether the call actually succeeded; a plain callable is always 'decided'."""
    if hasattr(judge, "decide"):
        return judge.decide(p.a_text, p.a_location(), p.b_text, p.b_location())
    return bool(judge(p.a_text, p.a_location(), p.b_text, p.b_location())), True


def prejudge(
    band: list[GoldPair],
    judge: Judge,
    cache: DecisionCache,
    *,
    concurrency: int = 8,
    save_path: Optional[Path] = None,
    save_every: int = 25,
    max_new: Optional[int] = None,
) -> tuple[int, int]:
    """Judge the (uncached) band pairs concurrently, filling ``cache``.

    LLM-judge latency dominates a validation pass, and the calls are independent,
    so they run in a thread pool (I/O-bound; the GIL is released during the HTTP
    wait). Verdicts are written from the calling thread only, so the cache stays
    consistent without locking.

    Resumability + cost-safety (matters for expensive providers):

    - **Only *decided* verdicts are cached.** A pair whose call errored or whose
      reply was unparseable is left uncached and counted as ``undecided`` — a
      re-run retries it instead of freezing a wrong DIFFERENT into the oracle.
    - With ``save_path`` the cache is flushed every ``save_every`` new verdicts
      **and on any interruption** (``try/finally``), so a crash/Ctrl-C loses at
      most ``save_every`` judgments; a re-run replays the rest and judges only
      what's left.

    Returns ``(made, undecided)``. A missing key raises :class:`JudgeConfigError`.
    """
    targets = []
    for p in band:
        fp_a = finding_fingerprint(p.a_text, p.a_location())
        fp_b = finding_fingerprint(p.b_text, p.b_location())
        if cache.get(fp_a, fp_b) is None:
            targets.append((p, fp_a, fp_b))
    if max_new is not None:
        targets = targets[:max_new]  # cap how many uncached pairs to attempt this run

    def work(item):
        p, fp_a, fp_b = item
        verdict, decided = _decide(judge, p)
        return fp_a, fp_b, verdict, decided

    made = 0
    undecided = 0

    def handle(result):
        nonlocal made, undecided
        fp_a, fp_b, verdict, decided = result
        if not decided:
            undecided += 1
            return
        cache.put(fp_a, fp_b, verdict)
        made += 1
        if save_path and save_every and made % save_every == 0:
            cache.save(save_path)

    try:
        if concurrency <= 1:
            # Sequential main-thread path. Some judged endpoints (observed with
            # GPT-5.x reasoning models) return empty 200s when requests are fired
            # truly back-to-back by a thread pool's ``map``; a plain sequential
            # loop with the natural per-iteration gap avoids that. Use
            # ``call_delay`` on the judge to space calls further if needed.
            for item in targets:
                handle(work(item))
        else:
            with ThreadPoolExecutor(max_workers=concurrency) as ex:
                for result in ex.map(work, targets):
                    handle(result)
    finally:
        if save_path and made:
            cache.save(save_path)
    return made, undecided


def evaluate(matcher: Matcher, pairs: list[GoldPair], use_cache: bool = False) -> tuple[PRReport, dict]:
    """Matcher predictions vs gold labels → P/R plus a per-method tally."""
    tp = fp = fn = tn = 0
    methods: dict[str, int] = {}
    for p in pairs:
        dec = matcher.decide_pair(
            p.a_text, p.a_location(), p.b_text, p.b_location(), use_cache=use_cache
        )
        methods[dec.method] = methods.get(dec.method, 0) + 1
        pred = dec.same
        if pred and p.label:
            tp += 1
        elif pred and not p.label:
            fp += 1
        elif not pred and p.label:
            fn += 1
        else:
            tn += 1
    return PRReport(len(pairs), tp, fp, fn, tn), methods


def band_verdicts(band: list[GoldPair], cache: DecisionCache) -> dict[str, Optional[bool]]:
    """Each band pair's cached verdict for one judge: ``pair_id -> bool | None``.

    ``None`` means that judge has no verdict for the pair (uncached/undecided).
    Used to line up multiple judges' verdicts for inter-judge agreement.
    """
    out: dict[str, Optional[bool]] = {}
    for p in band:
        fp_a = finding_fingerprint(p.a_text, p.a_location())
        fp_b = finding_fingerprint(p.b_text, p.b_location())
        out[p.pair_id] = cache.get(fp_a, fp_b)
    return out


def cohen_kappa(labels_a: list[bool], labels_b: list[bool]) -> float:
    """Cohen's κ between two binary label columns of equal length."""
    n = len(labels_a)
    if n == 0 or n != len(labels_b):
        raise ValueError("label columns must be equal, non-zero length")
    agree = sum(1 for x, y in zip(labels_a, labels_b) if x == y) / n
    pa = sum(labels_a) / n
    pb = sum(labels_b) / n
    # chance agreement for a binary label
    pe = pa * pb + (1 - pa) * (1 - pb)
    return 1.0 if pe == 1.0 else (agree - pe) / (1 - pe)


def self_agreement(
    matcher: Matcher, pairs: list[GoldPair], runs: int = 2, use_cache: bool = False
) -> dict:
    """Run the matcher ``runs`` times and measure verdict stability.

    With cache on (or a deterministic first pass / fallback) this is 1.0 by
    construction — the point of the design. With an LLM judge and cache off it
    exposes the judge's raw flip rate, the honest number to report.
    """
    cols: list[list[bool]] = []
    for _ in range(runs):
        cols.append(
            [
                matcher.decide_pair(
                    p.a_text, p.a_location(), p.b_text, p.b_location(), use_cache=use_cache
                ).same
                for p in pairs
            ]
        )
    flips = sum(1 for i in range(len(pairs)) if len({col[i] for col in cols}) > 1)
    n = len(pairs)
    return {
        "runs": runs,
        "n": n,
        "flipped": flips,
        "flip_rate": round(flips / n, 4) if n else 0.0,
        "self_agreement": round(1 - flips / n, 4) if n else 1.0,
    }


def threshold_sensitivity(
    pairs: list[GoldPair],
    tau_mid_grid: Iterable[float] = (0.30, 0.35, 0.40, 0.42, 0.45, 0.50, 0.55),
    tau_high: float = 0.60,
    tau_low: float = 0.25,
) -> list[dict]:
    """Recompute P/R over a grid of the deterministic matcher's decision boundary.

    With no LLM judge, the operative knob is ``tau_mid`` — the lexical-fallback
    boundary that decides every pair not already resolved by the ``tau_high``
    (auto-same) / ``tau_low`` (auto-different-if-disjoint) shortcuts. Sweeping it
    traces the precision/recall trade-off and shows how sharply — or not — the
    headline moves with the knob. (When the LLM judge is wired in, the analogous
    sweep perturbs the ``[tau_low, tau_high]`` band that gates escalation.)
    """
    rows: list[dict] = []
    for tm in tau_mid_grid:
        m = Matcher(judge=None, tau_high=tau_high, tau_low=tau_low, tau_mid=tm)
        report, _ = evaluate(m, pairs, use_cache=False)
        rows.append({"tau_mid": tm, **report.to_dict()})
    return rows
