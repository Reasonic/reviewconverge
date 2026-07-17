"""Lightweight configuration — load API keys from a git-ignored ``.env``.

Keys are read from the process environment (``ANTHROPIC_API_KEY`` /
``OPENAI_API_KEY`` / ``DEEPSEEK_API_KEY``). For convenience, :func:`load_dotenv`
also reads a ``.env`` file at the repo root so you can drop keys in one place
without exporting them each shell. Real environment variables take precedence
(``override=False``), so CI secrets are never clobbered by a stale file.

Stdlib only — no ``python-dotenv`` dependency (the repo keeps runtime deps empty
on purpose). The ``.env`` file is git-ignored; ``.env.example`` is the template.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# The provider keys the matcher's LLM judge (and the M2 loop) look up. GEMINI_API_KEY
# was added 2026-07-07 when Gemini 3.1 Pro replaced GPT-5.5 in the reasoning-arm + judge slots.
KEY_ENV_VARS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "GEMINI_API_KEY")


def default_env_path() -> Path:
    """``<repo-root>/.env`` — repo root is the parent of the package directory."""
    return Path(__file__).resolve().parent.parent / ".env"


def load_dotenv(path: Optional[Path] = None, *, override: bool = False) -> dict[str, str]:
    """Load ``KEY=value`` pairs from a ``.env`` file into ``os.environ``.

    Ignores blank lines and ``#`` comments; tolerates a leading ``export`` and
    surrounding quotes. Existing environment variables win unless ``override``.
    Returns the mapping that was read (values are NOT logged anywhere).
    """
    path = Path(path) if path is not None else default_env_path()
    if not path.exists():
        return {}
    loaded: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = value
        loaded[key] = value
    return loaded


def key_status() -> dict[str, bool]:
    """Which provider keys are currently visible (existence only, never values)."""
    return {name: bool(os.environ.get(name)) for name in KEY_ENV_VARS}
