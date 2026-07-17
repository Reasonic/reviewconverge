"""On-disk seeded-defect corpus: format, loader, and integrity validator.

The corpus is the ground truth every ReviewConverge number rests on, so its
on-disk format is a contract and its integrity is machine-checked (not trusted).

Layout
------
Each corpus *item* is a self-contained directory::

    corpus/<type>/<type>-NNNN/
        artifact.<ext>   # the reviewed artifact - the ONLY thing a review loop sees
        meta.json        # provenance + construction record + verified-clean regions
        defects.json     # the answer key: seeded ground-truth defects

``<type>`` is one of ``code`` / ``paper`` / ``spec``. ``artifact.<ext>`` is opaque
text (a unified diff, a Markdown excerpt, a YAML/TOML config, ...); the tooling
never parses it, so no format-specific dependency is needed.

Oracle-leak guard
-----------------
The review loop under test must see the artifact and nothing else - never the
answer key. That is enforced at the API boundary: the harness path calls
``CorpusItem.artifact_text()`` (reads only ``artifact.<ext>``), while the metric
path calls ``CorpusItem.defects`` (the seeded ground truth). Keep the harness off
``defects``/``meta`` entirely.

Oracle-hygiene gate
-------------------
Ground truth is *constructed*, never LLM-discovered: a frontier model may propose
candidates, but a human confirms each defect is (a) real, (b) findable from the
artifact alone, (c) uniquely describable. That confirmation is recorded per defect
as ``confirmed: true``. Unconfirmed defects are allowed *while building* the corpus
but the freeze step refuses to freeze until every defect is confirmed (see
``scripts/freeze_corpus.py``) - the frozen oracle is what all metrics trust.

This module is stdlib-only (JSON) so it imports anywhere, including validation CI.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

from .schema import Location, SeededDefect, Severity

#: Filename of the freeze manifest written at the corpus freeze (plan §4.1).
MANIFEST_NAME = "MANIFEST.sha256"

#: Recipe/format version. Bumped when the on-disk contract or taxonomy changes.
CORPUS_FORMAT_VERSION = "0.1.0"

#: The three artifact types (the cross-domain breadth is a headline differentiator).
ARTIFACT_TYPES = ("code", "paper", "spec")

#: Plan §4.1: k seeded defects per artifact, varied 3-8. Outside this range warns.
MIN_DEFECTS_PER_ITEM = 3
MAX_DEFECTS_PER_ITEM = 8

#: Plan §4.1: 2-3 paraphrase variants per defect (they seed the matcher gold set).
MIN_PARAPHRASES = 2
MAX_PARAPHRASES = 3

#: SPDX ids permissive enough to redistribute (modified) inside a CC-BY-4.0 corpus
#: with attribution. Copyleft (GPL/LGPL/MPL) and CC-BY-SA are excluded: they would
#: force their terms onto the released corpus. Used for `code` and `spec` items.
#: CC-BY-4.0/3.0, CC0, and public-domain are included too — some real config/code
#: sources (e.g. Kubernetes manifests from kubernetes/website) are CC-BY-4.0, which
#: is the corpus's own license and thus trivially compatible.
PERMISSIVE_CODE_LICENSES = frozenset({
    "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "0BSD",
    "Unlicense", "CC0-1.0", "PSF-2.0", "Python-2.0",
    "CC-BY-4.0", "CC-BY-3.0", "public-domain",
})

#: Licenses acceptable for redistributing a *modified prose excerpt* (`paper`
#: items). Stricter on purpose: the default arXiv "non-exclusive license to
#: distribute" does NOT grant redistribution of derivatives, and CC-BY-SA/-NC/-ND
#: are incompatible with a CC-BY-4.0 corpus. So paper bases must be CC-BY / CC0 /
#: public-domain (e.g. arXiv papers explicitly filed under CC-BY).
PERMISSIVE_PAPER_LICENSES = frozenset({
    "CC-BY-4.0", "CC-BY-3.0", "CC0-1.0", "public-domain",
})

#: Which license set applies to each artifact type.
LICENSE_ALLOWLIST = {
    "code": PERMISSIVE_CODE_LICENSES,
    "spec": PERMISSIVE_CODE_LICENSES,
    "paper": PERMISSIVE_PAPER_LICENSES,
}


class CorpusError(Exception):
    """Raised when a corpus item is structurally unloadable (missing/invalid files)."""


@dataclass
class ValidationIssue:
    """One problem found while validating a corpus item.

    ``level`` is ``"error"`` (blocks freeze / fails validation) or ``"warning"``
    (surfaced but non-blocking, e.g. a defect count outside the recommended band).
    """

    item_id: str
    level: str  # "error" | "warning"
    code: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"[{self.level}] {self.item_id}: {self.code} - {self.message}"


@dataclass
class CorpusItem:
    """One loaded corpus item: an artifact plus its seeded ground truth.

    ``defects`` are the interchange ``SeededDefect`` records the metric suite
    consumes. ``defect_records`` retains the raw JSON dicts (incl. construction
    provenance such as ``confirmed``/``rationale``) for audit + freeze tooling.
    """

    id: str
    type: str
    directory: Path
    artifact_file: str
    meta: dict[str, Any]
    defects: list[SeededDefect]
    defect_records: list[dict[str, Any]] = field(default_factory=list)

    @property
    def artifact_path(self) -> Path:
        return self.directory / self.artifact_file

    def artifact_text(self) -> str:
        """Return exactly the artifact text a review loop is allowed to see."""
        return self.artifact_path.read_text(encoding="utf-8")

    def unconfirmed_defect_ids(self) -> list[str]:
        """Defect ids not yet human-confirmed (the oracle-hygiene gate reads this)."""
        return [
            r.get("id", "<no-id>")
            for r in self.defect_records
            if not r.get("confirmed", False)
        ]

    def all_confirmed(self) -> bool:
        return not self.unconfirmed_defect_ids()

    @property
    def known_gray_zone(self) -> list[dict[str, Any]]:
        """Documented pre-existing debatable issues that are NOT seeded defects.

        Real artifacts carry plausible-but-unseeded issues (upstream smells, style
        nits). A reviewer may flag them, so scoring the false-finding-injection
        metric must exclude findings matching these regions rather than count them
        as hallucinations. Each entry is ``{"location": {...}, "note": str}``.
        """
        return list(self.meta.get("known_gray_zone", []))

    def line_map(self) -> dict[int, str]:
        """Map addressable line number -> content for the artifact.

        For ``code`` items the artifact is a unified diff, so lines are numbered by
        the **post-image** (new file), matching how defect locations are recorded.
        For ``paper``/``spec`` the artifact is raw text numbered 1..N.
        """
        text = self.artifact_text()
        return _diff_postimage_lines(text) if self.type == "code" else _raw_lines(text)

    def line_text(self, start: int, end: Optional[int] = None) -> str:
        """Concatenate the artifact lines in ``[start, end]`` (end defaults to start)."""
        lm = self.line_map()
        end = start if end is None else end
        return "\n".join(lm.get(i, "") for i in range(start, end + 1))


# --------------------------------------------------------------------------- #
# Line resolution (for anchor verification)
# --------------------------------------------------------------------------- #

def _raw_lines(text: str) -> dict[int, str]:
    return dict(enumerate(text.splitlines(), start=1))


def _diff_postimage_lines(diff_text: str) -> dict[int, str]:
    """Map post-image (new-file) line number -> content for a unified diff.

    Advances the new-file counter on context (' ') and added ('+') lines, skips
    removed ('-') lines, and (re)seats the counter from each ``@@ ... +c,d @@``
    hunk header. Robust to multi-hunk diffs; our code artifacts are new-file diffs.
    """
    out: dict[int, str] = {}
    new_no: Optional[int] = None
    for ln in diff_text.splitlines():
        if ln.startswith("@@"):
            try:
                plus = ln.split("+", 1)[1]
                new_no = int(plus.split(",", 1)[0].split(" ", 1)[0])
            except (IndexError, ValueError):
                new_no = None
            continue
        if new_no is None or ln.startswith("\\"):  # "\ No newline at end of file"
            continue
        if ln.startswith(("+", " ")):
            out[new_no] = ln[1:]
            new_no += 1
        # '-' lines exist only in the pre-image; they do not advance new_no.
    return out


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #

def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise CorpusError(f"missing required file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CorpusError(f"invalid JSON in {path}: {exc}") from exc


def _location_from_dict(d: dict[str, Any]) -> Location:
    return Location(unit=d["unit"], start=d.get("start"), end=d.get("end"))


def _defect_from_record(rec: dict[str, Any]) -> SeededDefect:
    return SeededDefect(
        id=rec["id"],
        description=rec["description"],
        location=_location_from_dict(rec["location"]),
        severity=Severity(rec["severity"]),
        category=rec.get("category"),
        paraphrases=list(rec.get("paraphrases", [])),
    )


def load_item(item_dir: Path) -> CorpusItem:
    """Load a single corpus item directory into a :class:`CorpusItem`.

    Raises :class:`CorpusError` on structural problems (missing files, bad JSON,
    missing required keys). Semantic problems (bad ranges, id mismatches, etc.)
    are reported non-fatally by :func:`validate_item`, so that a partially-built
    corpus can still be loaded and inspected during construction.
    """
    item_dir = Path(item_dir)
    meta = _read_json(item_dir / "meta.json")

    for key in ("id", "type", "artifact_file"):
        if key not in meta:
            raise CorpusError(f"{item_dir/'meta.json'}: missing required key '{key}'")

    defects_doc = _read_json(item_dir / "defects.json")
    records = defects_doc.get("defects", [])
    if not isinstance(records, list):
        raise CorpusError(f"{item_dir/'defects.json'}: 'defects' must be a list")

    defects: list[SeededDefect] = []
    for rec in records:
        try:
            defects.append(_defect_from_record(rec))
        except (KeyError, ValueError) as exc:
            raise CorpusError(
                f"{item_dir/'defects.json'}: malformed defect record {rec!r}: {exc}"
            ) from exc

    return CorpusItem(
        id=meta["id"],
        type=meta["type"],
        directory=item_dir,
        artifact_file=meta["artifact_file"],
        meta=meta,
        defects=defects,
        defect_records=records,
    )


def iter_item_dirs(corpus_root: Path) -> Iterator[Path]:
    """Yield every ``<type>/<type>-NNNN`` item directory under ``corpus_root``."""
    corpus_root = Path(corpus_root)
    for typ in ARTIFACT_TYPES:
        type_dir = corpus_root / typ
        if not type_dir.is_dir():
            continue
        for child in sorted(type_dir.iterdir()):
            if child.is_dir() and (child / "meta.json").exists():
                yield child


def load_corpus(corpus_root: Path) -> list[CorpusItem]:
    """Load every item under ``corpus_root`` (raises on the first structural error)."""
    return [load_item(d) for d in iter_item_dirs(corpus_root)]


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

def validate_item(item: CorpusItem) -> list[ValidationIssue]:
    """Return structural/semantic issues for one item (errors + warnings).

    An empty list means the item passes. Errors block freeze; warnings are
    surfaced but do not block (e.g. defect count outside the 3-8 band).
    """
    issues: list[ValidationIssue] = []

    def err(code: str, msg: str) -> None:
        issues.append(ValidationIssue(item.id, "error", code, msg))

    def warn(code: str, msg: str) -> None:
        issues.append(ValidationIssue(item.id, "warning", code, msg))

    # --- identity ---------------------------------------------------------- #
    if item.type not in ARTIFACT_TYPES:
        err("bad-type", f"type '{item.type}' not in {ARTIFACT_TYPES}")
    if item.directory.name != item.id:
        err("id-dir-mismatch",
            f"meta id '{item.id}' != directory name '{item.directory.name}'")
    if item.type in ARTIFACT_TYPES and item.directory.parent.name != item.type:
        err("type-dir-mismatch",
            f"item type '{item.type}' but parent dir '{item.directory.parent.name}'")

    # --- artifact ---------------------------------------------------------- #
    if not item.artifact_path.exists():
        err("missing-artifact", f"artifact file '{item.artifact_file}' not found")
    elif not item.artifact_path.read_text(encoding="utf-8").strip():
        err("empty-artifact", f"artifact file '{item.artifact_file}' is empty")

    # --- defect count band ------------------------------------------------- #
    n = len(item.defects)
    if n == 0:
        err("no-defects", "item has zero seeded defects")
    elif n < MIN_DEFECTS_PER_ITEM or n > MAX_DEFECTS_PER_ITEM:
        warn("defect-count-band",
             f"{n} defects outside recommended {MIN_DEFECTS_PER_ITEM}-{MAX_DEFECTS_PER_ITEM}")

    meta_count = item.meta.get("defect_count")
    if meta_count is not None and meta_count != n:
        err("defect-count-mismatch",
            f"meta.defect_count={meta_count} but defects.json has {n}")

    # --- per-defect checks ------------------------------------------------- #
    # Resolve the artifact line map once (post-image lines for code diffs) so
    # every defect's `anchor` can be checked against the text at its location.
    line_map: dict[int, str] = {}
    if item.artifact_path.exists():
        try:
            line_map = item.line_map()
        except Exception:  # a malformed artifact is already reported above
            line_map = {}

    seen_ids: set[str] = set()
    for rec, defect in zip(item.defect_records, item.defects):
        did = defect.id
        if did in seen_ids:
            err("duplicate-defect-id", f"defect id '{did}' repeats within item")
        seen_ids.add(did)
        if not did.startswith(item.id + "-"):
            err("defect-id-prefix",
                f"defect id '{did}' should be prefixed with item id '{item.id}-'")
        if not defect.description.strip():
            err("empty-description", f"defect '{did}' has empty description")
        if not defect.location.unit.strip():
            err("empty-location-unit", f"defect '{did}' has empty location.unit")
        # anchor: a substring that must appear at the defect's location — turns
        # location correctness into a machine check (the oracle-integrity guard).
        anchor = rec.get("anchor")
        if anchor:
            if defect.location.start is None:
                err("anchor-needs-line", f"defect '{did}' has an anchor but no location.start")
            elif line_map:
                span = "\n".join(
                    line_map.get(i, "")
                    for i in range(defect.location.start,
                                   (defect.location.end or defect.location.start) + 1)
                )
                if anchor not in span:
                    err("anchor-mismatch",
                        f"defect '{did}': anchor {anchor!r} not found at lines "
                        f"{defect.location.start}-{defect.location.end or defect.location.start}")
        if not defect.category:
            warn("missing-category", f"defect '{did}' has no category")
        npar = len(defect.paraphrases)
        if npar < MIN_PARAPHRASES or npar > MAX_PARAPHRASES:
            warn("paraphrase-count",
                 f"defect '{did}' has {npar} paraphrases "
                 f"(want {MIN_PARAPHRASES}-{MAX_PARAPHRASES})")
        if any(not p.strip() for p in defect.paraphrases):
            err("empty-paraphrase", f"defect '{did}' has a blank paraphrase")
        # A paraphrase identical to the canonical description teaches the matcher
        # nothing about equivalence - flag it.
        if defect.description.strip() in {p.strip() for p in defect.paraphrases}:
            warn("paraphrase-echoes-description",
                 f"defect '{did}' has a paraphrase identical to its description")

    # --- clean regions ----------------------------------------------------- #
    if not item.meta.get("clean_regions"):
        warn("no-clean-regions",
             "no verified-clean regions recorded (needed for false-finding scoring)")

    # --- known gray-zone entries (optional) -------------------------------- #
    gz = item.meta.get("known_gray_zone", [])
    if not isinstance(gz, list):
        err("bad-gray-zone", "known_gray_zone must be a list if present")
    else:
        for entry in gz:
            if not isinstance(entry, dict) or "note" not in entry or "location" not in entry:
                err("bad-gray-zone-entry",
                    f"known_gray_zone entry must have 'location' and 'note': {entry!r}")
            elif not str(entry.get("note", "")).strip():
                err("empty-gray-zone-note", "known_gray_zone entry has an empty note")

    # --- provenance / licensing ------------------------------------------- #
    # Real-derived items redistribute (modified) third-party content, so they must
    # carry enough provenance to attribute + license correctly. Synthetic items
    # are authored here and need none of this.
    source = item.meta.get("source", {})
    origin = source.get("origin")
    if origin not in ("synthetic", "derived"):
        err("bad-origin", f"source.origin must be 'synthetic' or 'derived', got {origin!r}")
    elif origin == "derived":
        for req in ("url", "license", "source_ref"):
            if not source.get(req):
                err("missing-provenance",
                    f"derived item missing source.{req} (required for attribution/license)")
        if not source.get("retrieved"):
            warn("missing-retrieved", "derived item has no source.retrieved date")
        if not source.get("attribution"):
            warn("missing-attribution",
                 "derived item has no source.attribution (author/owner for ATTRIBUTIONS.md)")
        lic = source.get("license")
        allowed = LICENSE_ALLOWLIST.get(item.type, PERMISSIVE_CODE_LICENSES)
        if lic and lic not in allowed:
            err("license-not-allowed",
                f"license '{lic}' not redistributable in a CC-BY-4.0 corpus for "
                f"type '{item.type}' (allowed: {sorted(allowed)})")

    return issues


def validate_corpus(corpus_root: Path) -> list[ValidationIssue]:
    """Validate every item plus corpus-wide invariants (globally unique defect ids)."""
    items = load_corpus(corpus_root)
    issues: list[ValidationIssue] = []

    global_ids: dict[str, str] = {}
    for item in items:
        issues.extend(validate_item(item))
        for defect in item.defects:
            if defect.id in global_ids:
                issues.append(ValidationIssue(
                    item.id, "error", "duplicate-defect-id-global",
                    f"defect id '{defect.id}' also used in item '{global_ids[defect.id]}'"))
            else:
                global_ids[defect.id] = item.id

    return issues


def unconfirmed_defects(corpus_root: Path) -> list[str]:
    """Every not-yet-human-confirmed defect id across the corpus (freeze gate)."""
    out: list[str] = []
    for item in load_corpus(corpus_root):
        out.extend(item.unconfirmed_defect_ids())
    return out


def errors_only(issues: list[ValidationIssue]) -> list[ValidationIssue]:
    return [i for i in issues if i.level == "error"]


# --------------------------------------------------------------------------- #
# Freeze + drift verification
# --------------------------------------------------------------------------- #
#
# The frozen, hashed corpus is the oracle every ReviewConverge number trusts, so
# these functions are the load-bearing part of the freeze/verify scripts and are
# kept in the package (not the CLI) so they are importable and unit-tested.

def manifest_entries(corpus_root: Path) -> list[tuple[str, str]]:
    """Return ``(relative_posix_path, sha256)`` for every corpus file.

    Sorted and manifest-excluded so the output is deterministic (stable hashing
    is what makes the freeze a meaningful fingerprint).
    """
    corpus_root = Path(corpus_root)
    entries: list[tuple[str, str]] = []
    for path in sorted(corpus_root.rglob("*")):
        if not path.is_file() or path.name == MANIFEST_NAME:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append((path.relative_to(corpus_root).as_posix(), digest))
    return entries


def render_manifest(entries: list[tuple[str, str]]) -> str:
    """Render entries in the ``sha256  path`` convention (one per line)."""
    return "".join(f"{digest}  {rel}\n" for rel, digest in entries)


def parse_manifest(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        digest, _, rel = line.partition("  ")
        out[rel] = digest
    return out


@dataclass
class FreezeResult:
    """Outcome of a freeze attempt."""

    ok: bool
    manifest_path: Optional[Path] = None
    n_files: int = 0
    errors: list[ValidationIssue] = field(default_factory=list)
    unconfirmed: list[str] = field(default_factory=list)


def freeze_blockers(corpus_root: Path) -> tuple[list[ValidationIssue], list[str]]:
    """Return ``(validation_errors, unconfirmed_defect_ids)`` — both empty ⇒ freezable.

    This is the oracle-hygiene gate: the corpus must validate clean *and* every
    seeded defect must be human-confirmed before it can be frozen.
    """
    errors = errors_only(validate_corpus(corpus_root))
    pending = unconfirmed_defects(corpus_root)
    return errors, pending


def freeze_corpus(corpus_root: Path) -> FreezeResult:
    """Freeze the corpus: write ``MANIFEST.sha256`` iff the gate passes.

    Refuses (``ok=False``, no manifest written) on an empty corpus, on validation
    errors, or on any unconfirmed defect.
    """
    corpus_root = Path(corpus_root)
    if not load_corpus(corpus_root):
        return FreezeResult(ok=False, errors=[ValidationIssue(
            "<corpus>", "error", "empty-corpus", "corpus has no items")])

    errors, pending = freeze_blockers(corpus_root)
    if errors or pending:
        return FreezeResult(ok=False, errors=errors, unconfirmed=pending)

    entries = manifest_entries(corpus_root)
    manifest_path = corpus_root / MANIFEST_NAME
    manifest_path.write_text(render_manifest(entries), encoding="utf-8")
    return FreezeResult(ok=True, manifest_path=manifest_path, n_files=len(entries))


@dataclass
class DriftResult:
    """Outcome of verifying a corpus against its frozen manifest."""

    ok: bool
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    n_files: int = 0


def verify_manifest(corpus_root: Path) -> DriftResult:
    """Recompute hashes and compare to ``MANIFEST.sha256`` (the drift guard).

    Raises :class:`CorpusError` if the corpus was never frozen. ``ok`` is True iff
    no file was added, removed, or changed since the freeze.
    """
    corpus_root = Path(corpus_root)
    manifest_path = corpus_root / MANIFEST_NAME
    if not manifest_path.exists():
        raise CorpusError(f"no {MANIFEST_NAME}: corpus is not frozen yet")

    recorded = parse_manifest(manifest_path.read_text(encoding="utf-8"))
    current = dict(manifest_entries(corpus_root))

    rp, cp = set(recorded), set(current)
    added = sorted(cp - rp)
    removed = sorted(rp - cp)
    changed = sorted(p for p in (rp & cp) if recorded[p] != current[p])
    return DriftResult(
        ok=not (added or removed or changed),
        added=added, removed=removed, changed=changed, n_files=len(recorded),
    )
