# Runs — released run logs

Every number in the paper is backed by a run log here, so results are reproducible
**without re-spending on APIs**. Each run is a serialized `RunTrajectory` (see
`reviewconverge.schema`) plus its config and cost accounting.

Planned structure:
- `baseline/`      — baseline-loop runs (M3): single-reviewer / panel × 3 artifact types
- `interventions/` — one subdir per intervention arm (M4)
- `INDEX.md`       — run id → (artifact, config, model, seed) → tables it backs

Provenance in every trajectory: artifact id, config id, model id, seed, and prompt
versions. `_scratch/` and `*.local.*` are gitignored; released logs are committed
deliberately.

## Status

🚧 Empty until M3 baseline runs.
