from __future__ import annotations

from types import SimpleNamespace

import pytest
from unittest.mock import patch

from hogli_commands import github_auth


@pytest.mark.parametrize(("env_var", "prefer_cli"), [("GH_TOKEN", False), ("GH_TOKEN", True), ("GITHUB_TOKEN", False)])
def test_env_token_wins_over_gh(monkeypatch: pytest.MonkeyPatch, env_var: str, prefer_cli: bool) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv(env_var, "env-tok")
    with patch.object(github_auth.subprocess, "run") as run:
        assert github_auth.github_token(prefer_cli=prefer_cli) == "env-tok"
    run.assert_not_called()


@pytest.mark.parametrize("application_token", [None, "app-tok"])
def test_falls_back_to_gh_cli(monkeypatch: pytest.MonkeyPatch, application_token: str | None) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    if application_token:
        monkeypatch.setenv("GITHUB_TOKEN", application_token)
    monkeypatch.setattr(github_auth.shutil, "which", lambda _: "/usr/bin/gh")
    with patch.object(
        github_auth.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="gh-tok\n")
    ) as run:
        assert github_auth.github_token(prefer_cli=bool(application_token)) == "gh-tok"
    assert "GITHUB_TOKEN" not in run.call_args.kwargs["env"]


@pytest.mark.parametrize("application_token", [None, "app-tok"])
@pytest.mark.parametrize("cli_available", [False, True])
def test_fallback_without_cli_login(
    monkeypatch: pytest.MonkeyPatch, application_token: str | None, cli_available: bool
) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    if application_token:
        monkeypatch.setenv("GITHUB_TOKEN", application_token)
    monkeypatch.setattr(github_auth.shutil, "which", lambda _: "/usr/bin/gh" if cli_available else None)
    with patch.object(github_auth.subprocess, "run", return_value=SimpleNamespace(returncode=1, stdout="")):
        assert github_auth.github_token(prefer_cli=True) == application_token


def test_headers_carry_bearer_only_with_a_token() -> None:
    # db_schema relies on the None case omitting Authorization (anonymous reads).
    assert github_auth.github_headers("tok")["Authorization"] == "Bearer tok"
    assert "Authorization" not in github_auth.github_headers(None)
