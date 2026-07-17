"""Tests for the .env loader (reviewconverge.config)."""

from __future__ import annotations

import os

from reviewconverge.config import KEY_ENV_VARS, key_status, load_dotenv


def test_load_dotenv_parses_and_respects_precedence(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "# a comment\n"
        "\n"
        'ANTHROPIC_API_KEY="sk-ant-xyz"\n'
        "export OPENAI_API_KEY = sk-openai-123 \n"
        "DEEPSEEK_API_KEY='sk-deepseek-abc'\n"
        "MALFORMED_LINE_NO_EQUALS\n",
        encoding="utf-8",
    )
    # Pre-set one var: an existing env value must win (override=False).
    monkeypatch.setenv("OPENAI_API_KEY", "already-set")
    for k in ("ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(k, raising=False)

    loaded = load_dotenv(env)
    assert loaded["ANTHROPIC_API_KEY"] == "sk-ant-xyz"       # quotes stripped
    assert loaded["OPENAI_API_KEY"] == "sk-openai-123"        # 'export ' + spaces handled
    assert loaded["DEEPSEEK_API_KEY"] == "sk-deepseek-abc"
    assert "MALFORMED_LINE_NO_EQUALS" not in loaded

    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-xyz"    # written to environ
    assert os.environ["OPENAI_API_KEY"] == "already-set"      # precedence: env wins


def test_load_dotenv_override(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("DEEPSEEK_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "from-env")
    load_dotenv(env, override=True)
    assert os.environ["DEEPSEEK_API_KEY"] == "from-file"


def test_load_dotenv_missing_file_is_noop(tmp_path):
    assert load_dotenv(tmp_path / "nope.env") == {}


def test_key_status_shape(monkeypatch):
    for k in KEY_ENV_VARS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    st = key_status()
    assert set(st) == set(KEY_ENV_VARS)
    assert st["ANTHROPIC_API_KEY"] is True
    assert st["OPENAI_API_KEY"] is False
