"""Deterministic similarity + location signals for the matcher's first pass.

The matcher resolves the *easy* finding pairs without an LLM (PLANS §4.3a.4b):
lexically near-identical claims are the same issue; claims that are both textually
dissimilar *and* anchored to disjoint locations are different. Only the ambiguous
middle band is escalated to the LLM judge. This module supplies those two
deterministic signals — a text-similarity score and a location-compatibility
verdict — and nothing else, so the first pass is pure, cheap, and reproducible.

Stdlib only (``difflib``), so it can run inside any environment. A stronger
embedding backend can later replace :func:`text_similarity` without touching the
matcher, which treats similarity as an opaque score in ``[0, 1]``.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from enum import Enum
from typing import Optional

from ..schema import Location

# Function words carry no discriminative signal for "same issue?" and would
# inflate token overlap between unrelated claims. Kept deliberately small — this
# is noise removal, not stemming.
_STOPWORDS = frozenset(
    """
    a an the this that these those of in on at to for from by with without and or
    but is are was were be been being it its as into than then so such not no
    all any each both here there which who whom whose what when where why how
    do does did done has have had having will would should could can may might
    """.split()
)

_WORD_RE = re.compile(r"[a-z0-9]+")
# Words OR discriminative comparison/arithmetic operators (longest match first, so
# ``<=`` wins over ``<``). Used only when ``keep_operators`` is set — the operators a
# code finding turns on (``n <= len`` vs ``n >= len``) are exactly what a punctuation-
# stripping normalize would erase, collapsing two opposite claims into one fingerprint.
_OP_TOKEN_RE = re.compile(r"[a-z0-9]+|<=|>=|==|!=|\+=|-=|\*=|/=|%=|<|>|\+|-|\*|/|%|=")


def normalize(text: str, keep_operators: bool = False) -> str:
    """Lowercase, drop punctuation, collapse whitespace — a canonical surface form.

    With ``keep_operators=True`` the comparison/arithmetic operators are retained as
    their own tokens, so claims that differ only by an operator (``n <= len`` vs
    ``n >= len``) do not normalize to the same string (audit #5). The default is
    unchanged so the content-addressed fingerprint — and any warm decision cache
    keyed by it — is bit-for-bit stable.
    """
    text = text.lower()
    if keep_operators:
        return " ".join(_OP_TOKEN_RE.findall(text))
    return " ".join(_WORD_RE.findall(text))


def content_tokens(text: str) -> frozenset[str]:
    """Distinct content words (stopwords removed) used for set-overlap scores."""
    return frozenset(t for t in _WORD_RE.findall(text.lower()) if t not in _STOPWORDS)


def _similarity_components(a: str, b: str) -> tuple[float, float, float]:
    """``(jaccard, sequence_ratio, overlap_coefficient)`` for two claims.

    Jaccard and the sequence ratio are **symmetric** (length-fair); the overlap
    coefficient ``|A∩B| / min(|A|,|B|)`` is **asymmetric** — it rewards a terse
    claim being contained in a longer one, which is useful for routing but must not
    on its own decide equivalence (see :func:`symmetric_similarity`).
    """
    A, B = content_tokens(a), content_tokens(b)
    seq = SequenceMatcher(None, normalize(a).split(), normalize(b).split()).ratio()
    if not A or not B:
        return 0.0, seq, 0.0
    inter = len(A & B)
    jaccard = inter / len(A | B)
    overlap = inter / min(len(A), len(B))
    return jaccard, seq, overlap


def text_similarity(a: str, b: str) -> float:
    """A lexical similarity score in ``[0, 1]`` robust to length asymmetry.

    Blends three views so no single failure mode dominates:

    - **Jaccard** over content tokens — order-independent, penalizes extra tokens.
    - **Overlap coefficient** (``|A∩B| / min(|A|,|B|)``) — tolerates a terse
      paraphrase being mostly contained in a longer canonical description
      (discounted ×0.85 so tiny token sets can't trivially score 1.0).
    - **Sequence ratio** over the normalized *token sequences* — rewards shared
      phrasing and word order that the set views ignore. Word-level (not
      character-level) so unrelated short strings that merely share letters and
      spaces ("alpha beta" vs "gamma delta") don't score spuriously high.

    The max of the three is returned: any one strong signal is enough to call a
    pair *lexically similar*. This is intentionally a recall-leaning first pass;
    the ambiguous band below :data:`~reviewconverge.matcher.core` thresholds is
    handed to the LLM judge rather than decided here.
    """
    jaccard, seq, overlap = _similarity_components(a, b)
    return max(jaccard, seq, 0.85 * overlap)


def symmetric_similarity(a: str, b: str) -> float:
    """Length-symmetric similarity: ``max(jaccard, sequence_ratio)``.

    Excludes the asymmetric overlap coefficient, so a terse finding that is merely a
    token-*subset* of a longer defect does **not** score high here. The matcher gates
    its judge-bypassing ``lexical-high`` verdict on this (in addition to
    :func:`text_similarity`), so a subset paraphrase is escalated to the LLM judge
    rather than auto-accepted as SAME on the strength of the overlap coefficient
    alone (audit #6).
    """
    jaccard, seq, _overlap = _similarity_components(a, b)
    return max(jaccard, seq)


class LocationCompat(str, Enum):
    """The deterministic location signal between two findings.

    - ``SAME``: same addressing ``unit`` and overlapping (or touching) spans.
      NOTE: this is *not* sufficient to declare two findings equivalent — several
      distinct seeded defects share a line (e.g. ``code-0002`` packs 4 defects in
      ~20 lines). It only *permits* a SAME verdict; semantics must still agree.
    - ``DISJOINT``: different units, or non-overlapping spans in the same unit.
      Combined with low text similarity this is enough to declare DIFFERENT.
    - ``UNKNOWN``: at least one finding is unlocalized, so location says nothing.
    """

    SAME = "same"
    DISJOINT = "disjoint"
    UNKNOWN = "unknown"


def _spans_overlap(a: Location, b: Location) -> bool:
    """Do two spans in the same unit touch or overlap? Missing bounds ⇒ whole unit."""
    if a.start is None or a.end is None or b.start is None or b.end is None:
        # One side spans the whole unit (no offsets); treat as overlapping.
        return True
    return a.start <= b.end and b.start <= a.end


def location_compatibility(a: Optional[Location], b: Optional[Location]) -> LocationCompat:
    """Classify the location relationship between two findings."""
    if a is None or b is None:
        return LocationCompat.UNKNOWN
    if a.unit != b.unit:
        return LocationCompat.DISJOINT
    return LocationCompat.SAME if _spans_overlap(a, b) else LocationCompat.DISJOINT
