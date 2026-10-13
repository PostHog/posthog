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
    """Default 200 + active introspection payload with expected fields.

    The default scope includes `streamlit:iframe` so existing "accept" tests
    don't need to opt in to the scope check. Tests that exercise wrong-scope
    rejection pass their own `scope=` override.
    """
    data = {
        "active": True,
        "token_type": "access_token",
        "scope": "streamlit:iframe",
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
    streamlit_auth_proxy._introspection_circuit.reset()
    monkeypatch.setattr(streamlit_auth_proxy, "POSTHOG_SITE_URL", "https://app.posthog.test")
    yield
    streamlit_auth_proxy._introspection_cache.clear()
    streamlit_auth_proxy._introspection_circuit.reset()


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
            expected_scope_component="streamlit:iframe",
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
            expected_scope_component="streamlit:iframe",
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
            expected_scope_component="streamlit:iframe",
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
            expected_scope_component="streamlit:iframe",
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
            expected_scope_component="streamlit:iframe",
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
            expected_scope_component="streamlit:iframe",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_rejects_token_with_bridge_scope_on_iframe_path(self):
        """A first-party OAuth token from the streamlit app with matching team
        and client_id but carrying the BRIDGE scope (`streamlit:bridge`) must
        be rejected on the iframe path. The B.2.5 scope split is meaningless
        unless the proxy enforces it — without this check, a leaked bridge
        token would unlock the iframe even though it was minted for the
        sandbox→PostHog backchannel hop.
        """
        session = _make_fake_session(
            status=200,
            body=_make_introspection_response(
                scope="query:read streamlit:bridge",
                scoped_teams=[42],
                client_id="posthog-streamlit-apps-first-party",
            ),
        )

        result = await streamlit_auth_proxy._introspect_token(
            session,
            "bridge-scope-token",
            team_id=42,
            expected_client_id="posthog-streamlit-apps-first-party",
            expected_scope_component="streamlit:iframe",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_rejects_token_with_only_query_read_scope(self):
        """Defensive: a token with just `query:read` (no streamlit:iframe /
        streamlit:bridge qualifier at all) must also be rejected on the
        iframe path. This catches pre-scope-split tokens and any third-party
        query:read token that happens to pass the client_id + team checks.
        """
        session = _make_fake_session(
            status=200,
            body=_make_introspection_response(
                scope="query:read",
                scoped_teams=[42],
                client_id="posthog-streamlit-apps-first-party",
            ),
        )

        result = await streamlit_auth_proxy._introspect_token(
            session,
            "plain-query-read-token",
            team_id=42,
            expected_client_id="posthog-streamlit-apps-first-party",
            expected_scope_component="streamlit:iframe",
        )

        assert result is None


class TestTokenInjectionHostScoping:
    """The HTML rewrite must only append auth tokens to same-origin relative
    URLs. A protocol-relative URL (//evil.com) or absolute URL points at a
    foreign host, so appending _posthog_token there would leak the viewer's
    token cross-origin."""

    MODAL_TOKEN = "modal-secret"
    POSTHOG_TOKEN = "posthog-secret"

    def _inject(self, body: str) -> str:
        return streamlit_auth_proxy._inject_token_into_html(
            body.encode("utf-8"), self.MODAL_TOKEN, self.POSTHOG_TOKEN
        ).decode("utf-8")

    def test_appends_token_to_same_origin_relative_url(self):
        out = self._inject('<html><head></head><body><img src="/static/logo.png"></body></html>')
        assert "/static/logo.png?_modal_connect_token=" in out

    def test_does_not_leak_token_to_protocol_relative_url(self):
        out = self._inject('<html><head></head><body><script src="//evil.com/x.js"></script></body></html>')
        assert "//evil.com/x.js?_modal_connect_token=" not in out

    def test_does_not_leak_token_to_absolute_url(self):
        out = self._inject('<html><head></head><body><img src="https://evil.com/x.png"></body></html>')
        assert "https://evil.com/x.png?_modal_connect_token=" not in out


class TestTokenInjectionWithoutModalToken:
    """Docker sandboxes have no Modal connect token. The shim must still inject
    the posthog token (gating on the modal token would leave every Streamlit
    sub-request unauthenticated on Docker)."""

    def test_injects_posthog_token_with_empty_modal_token(self):
        out = streamlit_auth_proxy._inject_token_into_html(
            b"<html><head></head><body><img src='/x.png'></body></html>", "", "ptok"
        ).decode()
        # posthog token still appended to relative URLs and JS shim present
        assert "_posthog_token=ptok" in out
        assert "<script>" in out
        # no empty modal token param leaks in
        assert "_modal_connect_token=" not in out

    def test_includes_modal_token_when_present(self):
        out = streamlit_auth_proxy._inject_token_into_html(
            b"<html><head></head><body><img src='/x.png'></body></html>", "mtok", "ptok"
        ).decode()
        assert "_modal_connect_token=mtok" in out
        assert "_posthog_token=ptok" in out


class TestAuthExemptPrefixes:
    def test_stcore_health_is_auth_exempt(self):
        # Streamlit's liveness probe must not require the token, or the iframe
        # 401s before the app loads.
        assert any("/_stcore/health".startswith(p) for p in streamlit_auth_proxy._AUTH_EXEMPT_PREFIXES)
