from __future__ import annotations

from types import SimpleNamespace

import pytest
from unittest.mock import patch

from hogli_commands import github_auth


def test_env_token_wins_over_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    # Env vars must take precedence so CI and explicit overrides work without gh.
    monkeypatch.setenv("GH_TOKEN", "env-tok")
    with patch.object(github_auth.subprocess, "run") as run:
        assert github_auth.github_token() == "env-tok"
    run.assert_not_called()


def test_falls_back_to_gh_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(github_auth.shutil, "which", lambda _: "/usr/bin/gh")
    with patch.object(github_auth.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="gh-tok\n")):
        assert github_auth.github_token() == "gh-tok"


def test_none_when_no_env_and_no_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(github_auth.shutil, "which", lambda _: None)
    assert github_auth.github_token() is None


def test_headers_carry_bearer_only_with_a_token() -> None:
    # db_schema relies on the None case omitting Authorization (anonymous reads).
    assert github_auth.github_headers("tok")["Authorization"] == "Bearer tok"
    assert "Authorization" not in github_auth.github_headers(None)
