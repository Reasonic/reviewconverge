"""Tests for the seeded-defect corpus: loader, validator, and freeze/drift guard.

These run against the *shipped* vertical-slice corpus (one item per type) so they
also serve as an integrity check on the exemplars themselves.
"""

import json
import shutil
from pathlib import Path

import pytest

from reviewconverge.corpus import (
    ARTIFACT_TYPES,
    MANIFEST_NAME,
    CorpusError,
    FreezeResult,
    errors_only,
    freeze_corpus,
    load_corpus,
    load_item,
    unconfirmed_defects,
    validate_corpus,
    validate_item,
    verify_manifest,
)
from reviewconverge.schema import Severity

CORPUS_ROOT = Path(__file__).resolve().parent.parent / "corpus"


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #

def test_loads_all_types_present():
    items = load_corpus(CORPUS_ROOT)
    types = {it.type for it in items}
    assert types == set(ARTIFACT_TYPES)  # code / paper / spec all represented
    assert len(items) >= 3  # grows as the corpus is populated


def test_code_item_defects_parse_into_schema():
    item = load_item(CORPUS_ROOT / "code" / "code-0001")
    assert item.id == "code-0001"
    assert len(item.defects) == 4
    d1 = next(d for d in item.defects if d.id == "code-0001-d1")
    assert d1.category == "off-by-one"
    assert d1.severity == Severity.MAJOR
    assert 2 <= len(d1.paraphrases) <= 3
    assert d1.location.unit == "src/window.py"


def test_artifact_text_reads_only_the_artifact():
    item = load_item(CORPUS_ROOT / "spec" / "spec-0001")
    text = item.artifact_text()
    # The reviewed artifact is present...
    assert "environment: production" in text
    # ...and the answer key never leaks through the artifact path.
    assert "confirmed" not in text
    assert "paraphrases" not in text


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

def test_shipped_corpus_has_no_validation_errors():
    issues = validate_corpus(CORPUS_ROOT)
    errs = errors_only(issues)
    assert errs == [], f"unexpected validation errors: {[str(e) for e in errs]}"


def test_every_seeded_defect_is_globally_unique():
    items = load_corpus(CORPUS_ROOT)
    ids = [d.id for it in items for d in it.defects]
    assert len(ids) == len(set(ids))


def test_every_defect_anchor_resolves_at_its_location():
    # Every shipped defect carries an anchor that must appear at its location —
    # the machine-checked oracle-integrity guard.
    for item in load_corpus(CORPUS_ROOT):
        for rec in item.defect_records:
            anchor = rec.get("anchor")
            assert anchor, f"{rec['id']} has no anchor"
            loc = rec["location"]
            span = item.line_text(loc["start"], loc.get("end"))
            assert anchor in span, f"{rec['id']}: anchor {anchor!r} not at {loc}"


def test_validator_catches_anchor_mismatch():
    item = load_item(CORPUS_ROOT / "code" / "code-0001")
    item.defect_records[0]["anchor"] = "not-present-in-artifact"
    codes = {i.code for i in validate_item(item) if i.level == "error"}
    assert "anchor-mismatch" in codes


def test_real_derived_items_carry_valid_provenance():
    for item_id in ("code-0002", "spec-0002"):
        typ = item_id.split("-")[0]
        item = load_item(CORPUS_ROOT / typ / item_id)
        src = item.meta["source"]
        assert src["origin"] == "derived"
        assert src["url"] and src["license"] and src["source_ref"]
        # No validation errors for a well-formed derived item.
        assert errors_only(validate_item(item)) == []
        # No-leak: nothing in the artifact reveals it is a benchmark item.
        text = item.artifact_text().lower()
        for banned in ("reviewconverge", "seeded", "injected", "defect"):
            assert banned not in text


def test_known_gray_zone_is_exposed_and_structured():
    # spec-0002 documents two upstream gray-zone smells; code-0002 has none.
    spec2 = load_item(CORPUS_ROOT / "spec" / "spec-0002")
    assert len(spec2.known_gray_zone) == 2
    for entry in spec2.known_gray_zone:
        assert entry["note"].strip()
        assert entry["location"]["unit"]
    assert load_item(CORPUS_ROOT / "code" / "code-0002").known_gray_zone == []


def test_validator_rejects_malformed_gray_zone(tmp_path):
    item_dir = tmp_path / "code" / "code-0003"
    item_dir.mkdir(parents=True)
    (item_dir / "artifact.diff").write_text("+ x\n", encoding="utf-8")
    (item_dir / "meta.json").write_text(json.dumps({
        "id": "code-0003", "type": "code", "artifact_file": "artifact.diff",
        "defect_count": 1, "clean_regions": [{"unit": "x", "start": 1, "end": 1}],
        "source": {"origin": "synthetic"},
        "known_gray_zone": [{"location": {"unit": "x", "start": 1}}],  # missing 'note'
    }), encoding="utf-8")
    (item_dir / "defects.json").write_text(json.dumps({
        "artifact_id": "code-0003",
        "defects": [{
            "id": "code-0003-d1", "category": "off-by-one", "severity": "minor",
            "description": "x", "location": {"unit": "x", "start": 1},
            "paraphrases": ["a", "b"], "confirmed": True,
        }],
    }), encoding="utf-8")
    codes = {i.code for i in validate_corpus(tmp_path) if i.level == "error"}
    assert "bad-gray-zone-entry" in codes


def _write_item(item_dir, meta, defects):
    item_dir.mkdir(parents=True)
    (item_dir / "artifact.diff").write_text("+ real code line\n", encoding="utf-8")
    (item_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (item_dir / "defects.json").write_text(json.dumps(defects), encoding="utf-8")


def test_validator_rejects_bad_license_and_missing_provenance(tmp_path):
    good_defect = {
        "id": "code-0002-d1", "category": "off-by-one", "severity": "minor",
        "description": "x", "location": {"unit": "f", "start": 1},
        "paraphrases": ["a", "b"], "confirmed": True,
    }
    # Copyleft license + missing url/source_ref on a derived item.
    _write_item(
        tmp_path / "code" / "code-0002",
        {"id": "code-0002", "type": "code", "artifact_file": "artifact.diff",
         "defect_count": 1, "clean_regions": [{"unit": "f", "start": 1, "end": 1}],
         "source": {"origin": "derived", "license": "GPL-3.0"}},
        {"artifact_id": "code-0002", "defects": [good_defect]},
    )
    codes = {i.code for i in validate_corpus(tmp_path) if i.level == "error"}
    assert "license-not-allowed" in codes
    assert "missing-provenance" in codes


def test_validator_flags_id_prefix_and_count(tmp_path):
    item_dir = tmp_path / "code" / "code-9999"
    item_dir.mkdir(parents=True)
    (item_dir / "artifact.diff").write_text("+ some added line\n", encoding="utf-8")
    (item_dir / "meta.json").write_text(json.dumps({
        "id": "code-9999", "type": "code", "artifact_file": "artifact.diff",
        "defect_count": 2, "clean_regions": [{"unit": "x", "start": 1, "end": 1}],
    }), encoding="utf-8")
    # Only one defect (meta says 2), and its id is not prefixed with the item id.
    (item_dir / "defects.json").write_text(json.dumps({
        "artifact_id": "code-9999",
        "defects": [{
            "id": "wrong-prefix-d1", "category": "off-by-one", "severity": "minor",
            "description": "x", "location": {"unit": "f", "start": 1},
            "paraphrases": ["a", "b"], "confirmed": True,
        }],
    }), encoding="utf-8")

    issues = validate_corpus(tmp_path)
    codes = {i.code for i in issues if i.level == "error"}
    assert "defect-id-prefix" in codes
    assert "defect-count-mismatch" in codes


# --------------------------------------------------------------------------- #
# Oracle-hygiene freeze gate + drift guard
# --------------------------------------------------------------------------- #

def test_shipped_corpus_is_fully_confirmed():
    # The 2026-07-05 oracle audit confirmed every seeded defect.
    assert unconfirmed_defects(CORPUS_ROOT) == []


def _set_confirmed(defects_json: Path, value: bool) -> None:
    doc = json.loads(defects_json.read_text(encoding="utf-8"))
    for rec in doc["defects"]:
        rec["confirmed"] = value
    defects_json.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def test_freeze_gate_blocks_on_any_unconfirmed_defect(tmp_path):
    root = tmp_path / "corpus"
    shutil.copytree(CORPUS_ROOT, root)
    # The shipped corpus is frozen, so drop the copied manifest to model a
    # pre-freeze corpus (this test is about the gate refusing, not drift).
    (root / MANIFEST_NAME).unlink(missing_ok=True)
    # Un-confirm a single item -> the oracle-hygiene gate must refuse the freeze.
    _set_confirmed(root / "code" / "code-0001" / "defects.json", False)
    result = freeze_corpus(root)
    assert isinstance(result, FreezeResult)
    assert result.ok is False
    assert result.unconfirmed  # lists the un-confirmed defect ids
    assert not (root / MANIFEST_NAME).exists()


def test_freeze_then_verify_roundtrip_and_drift(tmp_path):
    root = tmp_path / "corpus"
    shutil.copytree(CORPUS_ROOT, root)

    # The shipped corpus is fully confirmed, so the freeze succeeds directly.
    result = freeze_corpus(root)
    assert result.ok is True
    assert (root / MANIFEST_NAME).exists()
    assert result.n_files > 0

    # A fresh verify sees no drift.
    assert verify_manifest(root).ok is True

    # Mutating any artifact is detected as drift.
    art = root / "spec" / "spec-0001" / "artifact.yaml"
    art.write_text(art.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")
    drift = verify_manifest(root)
    assert drift.ok is False
    assert any("spec-0001" in p for p in drift.changed)


def test_verify_without_manifest_raises(tmp_path):
    root = tmp_path / "corpus"
    shutil.copytree(CORPUS_ROOT, root)
    # Drop the shipped manifest so this exercises the "never frozen" path.
    (root / MANIFEST_NAME).unlink(missing_ok=True)
    with pytest.raises(CorpusError):
        verify_manifest(root)
