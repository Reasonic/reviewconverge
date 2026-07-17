"""Smoke tests for the finding-record schema (the one module implemented pre-M2)."""

from reviewconverge.schema import (
    Finding,
    Location,
    RoundFindingSet,
    RunTrajectory,
    SeededDefect,
    Severity,
    SCHEMA_VERSION,
)


def test_finding_roundtrips_to_dict():
    f = Finding(
        id="f1",
        claim="Possible race in cache invalidation.",
        location=Location(unit="cache.py", start=40, end=52),
        severity=Severity.MAJOR,
        evidence="Two threads write `self._map` without a lock.",
    )
    d = f.to_dict()
    assert d["id"] == "f1"
    assert d["location"]["unit"] == "cache.py"
    assert d["severity"] == Severity.MAJOR


def test_trajectory_serializes():
    traj = RunTrajectory(
        run_id="r1",
        artifact_id="code/0001",
        config_id="baseline-single",
        model_id="small-x",
        seed=7,
        rounds=[
            RoundFindingSet(round_index=0, findings=[Finding(id="f1", claim="a")]),
            RoundFindingSet(round_index=1, findings=[]),
        ],
    )
    d = traj.to_dict()
    assert len(d["rounds"]) == 2
    assert d["rounds"][0]["findings"][0]["claim"] == "a"


def test_seeded_defect_holds_paraphrases():
    defect = SeededDefect(
        id="d1",
        description="Off-by-one in loop bound.",
        location=Location(unit="scan.py", start=12),
        severity=Severity.MAJOR,
        paraphrases=["Loop overruns by one element.", "Index exceeds array length."],
    )
    assert len(defect.paraphrases) == 2


def test_schema_version_exposed():
    assert isinstance(SCHEMA_VERSION, str)
