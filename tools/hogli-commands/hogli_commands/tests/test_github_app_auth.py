from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import click
from hogli_commands import github_app_auth
from hogli_commands.github_app_auth import (
    CLIENT_ID_ENV_VAR,
    DeviceAuthorization,
    _write_cached_token,
    cached_token,
    poll_for_access_token,
    run_device_login,
    token_for_mode,
)

CLIENT_ID = "Iv1.test-client-id"
DEVICE = DeviceAuthorization(
    device_code="dc", user_code="ABCD-1234", verification_uri="https://gh/", expires_in=900, interval=5
)


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return self._payload


@pytest.fixture(autouse=True)
def app_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(CLIENT_ID_ENV_VAR, CLIENT_ID)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(github_app_auth, "TOKEN_CACHE_PATH", tmp_path / "github-app-token.json")


def _poll(monkeypatch: pytest.MonkeyPatch, responses: list[dict[str, Any]]) -> tuple[tuple[str, int], list[float]]:
    queue = [FakeResponse(r) for r in responses]
    clock = {"now": 0.0}
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock["now"] += seconds

    monkeypatch.setattr(github_app_auth.requests, "post", lambda url, **kwargs: queue.pop(0))
    result = poll_for_access_token(DEVICE, sleep=sleep, monotonic=lambda: clock["now"])
    return result, sleeps


class TestDeviceFlowPolling:
    def test_pending_then_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result, _sleeps = _poll(
            monkeypatch,
            [
                {"error": "authorization_pending"},
                {"access_token": "ghu_tok", "expires_in": 28800, "refresh_token": "ghr_secret"},
            ],
        )
        assert result == ("ghu_tok", 28800)

    def test_slow_down_raises_interval(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _result, sleeps = _poll(
            monkeypatch,
            [
                {"error": "slow_down", "interval": 12},
                {"access_token": "ghu_tok", "expires_in": 28800},
            ],
        )
        assert sleeps == [5.0, 12.0]

    @pytest.mark.parametrize(
        ("payload", "message_fragment"),
        [
            ({"error": "expired_token"}, "expired"),
            ({"error": "access_denied"}, "declined"),
            ({"error": "incorrect_client_credentials", "error_description": "bad app"}, "bad app"),
            ({"access_token": "ghu_tok"}, "Expire user authorization tokens"),
        ],
        ids=["expired_code", "denied", "other_error", "non_expiring_token"],
    )
    def test_terminal_errors(
        self, monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any], message_fragment: str
    ) -> None:
        with pytest.raises(click.ClickException, match=message_fragment):
            _poll(monkeypatch, [payload])

    def test_deadline_exceeded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(click.ClickException, match="Timed out"):
            _poll(monkeypatch, [{"error": "authorization_pending"}] * 200)


class TestTokenCache:
    def test_roundtrip_is_0600_and_drops_refresh_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def post(url: str, **kwargs: Any) -> FakeResponse:
            if url == github_app_auth.DEVICE_CODE_URL:
                return FakeResponse(
                    {
                        "device_code": "dc",
                        "user_code": "AB",
                        "verification_uri": "https://gh/",
                        "expires_in": 900,
                        "interval": 0,
                    }
                )
            return FakeResponse({"access_token": "ghu_tok", "expires_in": 28800, "refresh_token": "ghr_secret"})

        monkeypatch.setattr(github_app_auth.requests, "post", post)
        monkeypatch.setattr(github_app_auth.webbrowser, "open", lambda url: True)
        monkeypatch.setattr(github_app_auth.time, "sleep", lambda seconds: None)

        run_device_login()

        raw = github_app_auth.TOKEN_CACHE_PATH.read_text()
        assert "refresh" not in raw and "ghr_" not in raw
        assert github_app_auth.TOKEN_CACHE_PATH.stat().st_mode & 0o777 == 0o600
        assert cached_token() == "ghu_tok"

    @pytest.mark.parametrize(
        ("age_from_expiry", "expected"),
        [
            (timedelta(hours=-4), "ghu_tok"),
            (timedelta(minutes=-5), None),
            (timedelta(hours=1), None),
        ],
        ids=["fresh", "inside_safety_margin", "expired"],
    )
    def test_expiry_and_safety_margin(self, age_from_expiry: timedelta, expected: str | None) -> None:
        now = datetime.now(UTC)
        _write_cached_token("ghu_tok", now - age_from_expiry)
        assert cached_token(now=now) == expected

    @pytest.mark.parametrize(
        "content",
        [
            "not json",
            json.dumps({"token": "ghu_tok"}),
            json.dumps({"token": "ghu_tok", "expires_at": "2030-01-01T00:00:00+00:00", "client_id": "Iv1.other-app"}),
        ],
        ids=["corrupt", "missing_fields", "client_id_mismatch"],
    )
    def test_unusable_cache_returns_none(self, content: str) -> None:
        github_app_auth.TOKEN_CACHE_PATH.write_text(content)
        assert cached_token() is None

    def test_login_fast_path_skips_network(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_cached_token("ghu_tok", datetime.now(UTC) + timedelta(hours=4))
        monkeypatch.setattr(
            github_app_auth.requests, "post", lambda *a, **k: pytest.fail("device flow started despite valid cache")
        )
        run_device_login()


class TestTokenForMode:
    @pytest.mark.parametrize(
        ("mode", "cache", "env", "gh", "expected"),
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
        cache: bool,
        env: bool,
        gh: bool,
        expected: tuple[str, str] | None,
    ) -> None:
        if cache:
            _write_cached_token("app-tok", datetime.now(UTC) + timedelta(hours=4))
        if env:
            monkeypatch.setenv("GH_TOKEN", "env-tok")
        monkeypatch.setattr(github_app_auth, "gh_cli_token", lambda: "gh-tok" if gh else None)
        assert token_for_mode(mode) == expected  # type: ignore[arg-type]
