"""Unit tests for the in-sandbox auth proxy (streamlit_auth_proxy.py).

The proxy runs as a standalone Python process inside the Modal sandbox, so
it isn't exercised end-to-end in CI. These tests exercise its helper
functions directly — mainly the startup config check and the introspection
validator — because they gate auth decisions and are the highest-risk code
paths.
"""

import json

import pytest
from unittest import mock

from products.tasks.backend.sandbox.images import streamlit_auth_proxy


def _make_introspection_response(**overrides):
    """Default 200 + active introspection payload with expected fields."""
    data = {
        "active": True,
        "token_type": "access_token",
        "scope": "query:read",
        "scoped_teams": [42],
        "client_id": "posthog-streamlit-apps-first-party",
        "exp": 99999999999,
    }
    data.update(overrides)
    return json.dumps(data).encode("utf-8")


def _make_fake_session(*, status: int, body: bytes):
    """Build a MagicMock aiohttp.ClientSession whose .post() returns an async
    context manager yielding a response object with `.status` and `.read()`.
    """
    resp = mock.MagicMock()
    resp.status = status
    resp.read = mock.AsyncMock(return_value=body)

    cm = mock.MagicMock()
    cm.__aenter__ = mock.AsyncMock(return_value=resp)
    cm.__aexit__ = mock.AsyncMock(return_value=None)

    session = mock.MagicMock()
    session.post = mock.MagicMock(return_value=cm)
    return session


@pytest.fixture(autouse=True)
def _reset_proxy_module_state(monkeypatch):
    """Every test starts from a clean cache / circuit-breaker state and a
    POSTHOG_SITE_URL set so _introspect_token doesn't short-circuit."""
    streamlit_auth_proxy._introspection_cache.clear()
    streamlit_auth_proxy._introspection_circuit["failures"] = 0.0
    streamlit_auth_proxy._introspection_circuit["open_until"] = 0.0
    monkeypatch.setattr(streamlit_auth_proxy, "POSTHOG_SITE_URL", "https://app.posthog.test")
    yield
    streamlit_auth_proxy._introspection_cache.clear()
    streamlit_auth_proxy._introspection_circuit["failures"] = 0.0
    streamlit_auth_proxy._introspection_circuit["open_until"] = 0.0


# ---------- create_app() startup config validation ----------


class TestCreateAppConfigValidation:
    def test_raises_when_team_id_missing(self, monkeypatch):
        monkeypatch.delenv("POSTHOG_TEAM_ID", raising=False)
        monkeypatch.setenv("POSTHOG_STREAMLIT_CLIENT_ID", "posthog-streamlit-apps-first-party")

        with pytest.raises(RuntimeError, match="POSTHOG_TEAM_ID"):
            streamlit_auth_proxy.create_app()

    def test_raises_when_team_id_is_zero(self, monkeypatch):
        monkeypatch.setenv("POSTHOG_TEAM_ID", "0")
        monkeypatch.setenv("POSTHOG_STREAMLIT_CLIENT_ID", "posthog-streamlit-apps-first-party")

        with pytest.raises(RuntimeError, match="POSTHOG_TEAM_ID"):
            streamlit_auth_proxy.create_app()

    def test_raises_when_team_id_is_non_numeric(self, monkeypatch):
        monkeypatch.setenv("POSTHOG_TEAM_ID", "not-a-number")
        monkeypatch.setenv("POSTHOG_STREAMLIT_CLIENT_ID", "posthog-streamlit-apps-first-party")

        with pytest.raises(RuntimeError, match="POSTHOG_TEAM_ID"):
            streamlit_auth_proxy.create_app()

    def test_raises_when_client_id_missing(self, monkeypatch):
        monkeypatch.setenv("POSTHOG_TEAM_ID", "42")
        monkeypatch.delenv("POSTHOG_STREAMLIT_CLIENT_ID", raising=False)

        with pytest.raises(RuntimeError, match="POSTHOG_STREAMLIT_CLIENT_ID"):
            streamlit_auth_proxy.create_app()

    def test_raises_when_client_id_is_empty_string(self, monkeypatch):
        monkeypatch.setenv("POSTHOG_TEAM_ID", "42")
        monkeypatch.setenv("POSTHOG_STREAMLIT_CLIENT_ID", "")

        with pytest.raises(RuntimeError, match="POSTHOG_STREAMLIT_CLIENT_ID"):
            streamlit_auth_proxy.create_app()

    def test_succeeds_with_valid_env(self, monkeypatch):
        monkeypatch.setenv("POSTHOG_TEAM_ID", "42")
        monkeypatch.setenv("POSTHOG_STREAMLIT_CLIENT_ID", "posthog-streamlit-apps-first-party")

        app = streamlit_auth_proxy.create_app()

        assert app["posthog_team_id"] == 42
        assert app["posthog_streamlit_client_id"] == "posthog-streamlit-apps-first-party"


# ---------- _introspect_token cross-app and team binding ----------


class TestIntrospectTokenSecurity:
    @pytest.mark.asyncio
    async def test_accepts_token_with_matching_team_and_client_id(self):
        session = _make_fake_session(
            status=200,
            body=_make_introspection_response(
                scoped_teams=[42],
                client_id="posthog-streamlit-apps-first-party",
            ),
        )

        result = await streamlit_auth_proxy._introspect_token(
            session,
            "valid-token",
            team_id=42,
            expected_client_id="posthog-streamlit-apps-first-party",
        )

        assert result is not None
        assert result["active"] is True

    @pytest.mark.asyncio
    async def test_rejects_token_from_other_application(self):
        """A first-party OAuth token with matching team scope but a different
        application client_id (e.g. the MCP app) must be rejected — otherwise
        any token with query:read and the right team could unlock any sandbox.
        """
        session = _make_fake_session(
            status=200,
            body=_make_introspection_response(
                scoped_teams=[42],
                client_id="some-other-posthog-app",
            ),
        )

        result = await streamlit_auth_proxy._introspect_token(
            session,
            "cross-app-token",
            team_id=42,
            expected_client_id="posthog-streamlit-apps-first-party",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_rejects_token_with_missing_client_id(self):
        """Defensive: if the introspection response omits client_id entirely,
        reject (don't compare None == str and accept)."""
        body = json.dumps(
            {
                "active": True,
                "scope": "query:read",
                "scoped_teams": [42],
                # no client_id
            }
        ).encode("utf-8")
        session = _make_fake_session(status=200, body=body)

        result = await streamlit_auth_proxy._introspect_token(
            session,
            "missing-client-id-token",
            team_id=42,
            expected_client_id="posthog-streamlit-apps-first-party",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_rejects_token_from_other_team(self):
        session = _make_fake_session(
            status=200,
            body=_make_introspection_response(
                scoped_teams=[99],  # wrong team
                client_id="posthog-streamlit-apps-first-party",
            ),
        )

        result = await streamlit_auth_proxy._introspect_token(
            session,
            "cross-team-token",
            team_id=42,
            expected_client_id="posthog-streamlit-apps-first-party",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_rejects_inactive_token(self):
        session = _make_fake_session(
            status=200,
            body=_make_introspection_response(active=False),
        )

        result = await streamlit_auth_proxy._introspect_token(
            session,
            "inactive-token",
            team_id=42,
            expected_client_id="posthog-streamlit-apps-first-party",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_rejects_token_when_introspection_returns_non_200(self):
        session = _make_fake_session(status=500, body=b'{"error":"boom"}')

        result = await streamlit_auth_proxy._introspect_token(
            session,
            "upstream-500-token",
            team_id=42,
            expected_client_id="posthog-streamlit-apps-first-party",
        )

        assert result is None
