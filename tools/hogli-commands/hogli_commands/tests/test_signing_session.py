from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hogli_commands import github_app_auth, signing_session
from hogli_commands.github_app_auth import GitHubApp, write_cached_token
from hogli_commands.signing_session import CLIENT_ID_ENV_VAR, run_device_login, token_for_mode

CLIENT_ID = "Iv1.test-client-id"


@pytest.fixture(autouse=True)
def session_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(CLIENT_ID_ENV_VAR, CLIENT_ID)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(signing_session, "TOKEN_CACHE_PATH", tmp_path / "github-app-token.json")


def _start_session(token: str = "app-tok") -> None:
    app = GitHubApp(client_id=CLIENT_ID, token_cache_path=signing_session.TOKEN_CACHE_PATH)
    write_cached_token(app, token, datetime.now(UTC) + timedelta(hours=4))


class TestTokenForMode:
    @pytest.mark.parametrize(
        ("mode", "session", "env", "gh", "expected"),
        [
            ("auto", True, True, True, ("app-tok", "app")),
            ("auto", False, True, True, ("env-tok", "env")),
            ("auto", False, False, True, ("gh-tok", "gh")),
            ("auto", False, False, False, None),
            ("app", False, True, True, None),
            ("app", True, False, False, ("app-tok", "app")),
            ("env", False, False, True, None),
            ("gh", True, True, True, ("gh-tok", "gh")),
        ],
        ids=[
            "auto_prefers_app",
            "auto_env_over_gh",
            "auto_gh_fallback",
            "auto_nothing",
            "app_never_falls_through",
            "app_hit",
            "env_never_falls_through",
            "gh_ignores_app_and_env",
        ],
    )
    def test_precedence(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mode: str,
        session: bool,
        env: bool,
        gh: bool,
        expected: tuple[str, str] | None,
    ) -> None:
        if session:
            _start_session()
        if env:
            monkeypatch.setenv("GH_TOKEN", "env-tok")
        monkeypatch.setattr(signing_session, "gh_cli_token", lambda: "gh-tok" if gh else None)
        assert token_for_mode(mode) == expected  # type: ignore[arg-type]

    def test_no_registered_app_means_no_app_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _start_session()
        monkeypatch.delenv(CLIENT_ID_ENV_VAR)
        monkeypatch.setattr(signing_session, "gh_cli_token", lambda: None)
        assert token_for_mode("auto") is None


class TestRunDeviceLogin:
    def test_active_session_skips_network(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _start_session()
        monkeypatch.setattr(
            github_app_auth.requests, "post", lambda *a, **k: pytest.fail("device flow started despite active session")
        )
        run_device_login()
