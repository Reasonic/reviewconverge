"""ReviewConverge: a convergence benchmark and workflow standard for iterative agentic review.

Public API is intentionally small and grows as milestones land:

- ``reviewconverge.schema``  — the finding-record interchange format (M1)
- ``reviewconverge.corpus``  — seeded-defect corpus format, loader, validator (M1)
- ``reviewconverge.harness`` — iterative-review loop runner + per-round logging (M2)
- ``reviewconverge.matcher`` — finding-equivalence matcher + validation (M1b)
- ``reviewconverge.metrics`` — metric suite + regime classifier (M3)
"""

__version__ = "0.0.1"
