from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import click
from hogli_commands import github_app_auth
from hogli_commands.github_app_auth import (
    DeviceAuthorization,
    GitHubApp,
    cached_token,
    mint_user_token,
    poll_for_access_token,
    write_cached_token,
)

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


@pytest.fixture
def app(tmp_path: Path) -> GitHubApp:
    return GitHubApp(client_id="Iv1.test-client-id", token_cache_path=tmp_path / "token.json")


def _poll(
    monkeypatch: pytest.MonkeyPatch, app: GitHubApp, responses: list[dict[str, Any]]
) -> tuple[tuple[str, int], list[float]]:
    queue = [FakeResponse(r) for r in responses]
    clock = {"now": 0.0}
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock["now"] += seconds

    monkeypatch.setattr(github_app_auth.requests, "post", lambda url, **kwargs: queue.pop(0))
    result = poll_for_access_token(app, DEVICE, sleep=sleep, monotonic=lambda: clock["now"])
    return result, sleeps


class TestDeviceFlowPolling:
    def test_pending_then_success(self, monkeypatch: pytest.MonkeyPatch, app: GitHubApp) -> None:
        result, _sleeps = _poll(
            monkeypatch,
            app,
            [
                {"error": "authorization_pending"},
                {"access_token": "ghu_tok", "expires_in": 28800, "refresh_token": "ghr_secret"},
            ],
        )
        assert result == ("ghu_tok", 28800)

    def test_slow_down_raises_interval(self, monkeypatch: pytest.MonkeyPatch, app: GitHubApp) -> None:
        _result, sleeps = _poll(
            monkeypatch,
            app,
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
        self, monkeypatch: pytest.MonkeyPatch, app: GitHubApp, payload: dict[str, Any], message_fragment: str
    ) -> None:
        with pytest.raises(click.ClickException, match=message_fragment):
            _poll(monkeypatch, app, [payload])

    def test_deadline_exceeded(self, monkeypatch: pytest.MonkeyPatch, app: GitHubApp) -> None:
        with pytest.raises(click.ClickException, match="Timed out"):
            _poll(monkeypatch, app, [{"error": "authorization_pending"}] * 200)


class TestTokenCache:
    def test_mint_caches_0600_and_drops_refresh_token(self, monkeypatch: pytest.MonkeyPatch, app: GitHubApp) -> None:
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

        token, _expires_at = mint_user_token(app, open_browser=False)

        assert token == "ghu_tok"
        raw = app.token_cache_path.read_text()
        assert "refresh" not in raw and "ghr_" not in raw
        assert app.token_cache_path.stat().st_mode & 0o777 == 0o600
        assert cached_token(app) == "ghu_tok"

    @pytest.mark.parametrize(
        ("age_from_expiry", "expected"),
        [
            (timedelta(hours=-4), "ghu_tok"),
            (timedelta(minutes=-5), None),
            (timedelta(hours=1), None),
        ],
        ids=["fresh", "inside_safety_margin", "expired"],
    )
    def test_expiry_and_safety_margin(self, app: GitHubApp, age_from_expiry: timedelta, expected: str | None) -> None:
        now = datetime.now(UTC)
        write_cached_token(app, "ghu_tok", now - age_from_expiry)
        assert cached_token(app, now=now, safety_margin=timedelta(minutes=10)) == expected

    @pytest.mark.parametrize(
        "content",
        [
            "not json",
            json.dumps({"token": "ghu_tok"}),
            json.dumps({"token": "ghu_tok", "expires_at": "2030-01-01T00:00:00+00:00", "client_id": "Iv1.other-app"}),
        ],
        ids=["corrupt", "missing_fields", "client_id_mismatch"],
    )
    def test_unusable_cache_returns_none(self, app: GitHubApp, content: str) -> None:
        app.token_cache_path.write_text(content)
        assert cached_token(app) is None
