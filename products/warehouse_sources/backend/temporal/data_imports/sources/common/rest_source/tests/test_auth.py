from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAuth2Auth,
    OAuth2AuthRequestError,
)

AUTH_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth"


def _token_response(status_code: int = 200, payload: Optional[dict[str, Any]] = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload if payload is not None else {}
    return response


def _apply_auth(auth: OAuth2Auth) -> Optional[str]:
    """Run the auth against a prepared request and return the Authorization header it set."""
    request = MagicMock()
    request.headers = {}
    auth(request)
    return request.headers.get("Authorization")


class TestOAuth2Auth(SimpleTestCase):
    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_client_credentials_sets_bearer_and_caches(self, mock_session):
        mock_session.return_value.post.return_value = _token_response(
            payload={"access_token": "minted-123", "expires_in": 3600}
        )
        auth = OAuth2Auth(
            token_url="https://auth.example.com/token",
            client_id="cid",
            client_secret="csecret",
            grant_type="client_credentials",
        )
        assert _apply_auth(auth) == "Bearer minted-123"
        body = mock_session.return_value.post.call_args.kwargs["data"]
        assert body["grant_type"] == "client_credentials"
        assert body["client_id"] == "cid"
        assert body["client_secret"] == "csecret"
        # The token is cached for the run — a second request mints nothing new.
        assert _apply_auth(auth) == "Bearer minted-123"
        assert mock_session.return_value.post.call_count == 1

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_refresh_token_grant_body_and_no_in_memory_rotation(self, mock_session):
        mock_session.return_value.post.return_value = _token_response(
            payload={"access_token": "minted-456", "expires_in": 3600, "refresh_token": "refresh-rotated"}
        )
        auth = OAuth2Auth(
            token_url="https://auth.example.com/token",
            client_id="cid",
            client_secret="csecret",
            grant_type="refresh_token",
            refresh_token="refresh-orig",
        )
        assert _apply_auth(auth) == "Bearer minted-456"
        body = mock_session.return_value.post.call_args.kwargs["data"]
        assert body["grant_type"] == "refresh_token"
        assert body["refresh_token"] == "refresh-orig"
        # The auth object never rotates its in-memory refresh token, even when the response
        # returns a new one — rotation writeback is a Phase 2 sync-activity concern, not the
        # auth object's. Mutating it here would silently diverge from the persisted value.
        assert auth.refresh_token == "refresh-orig"

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_remints_when_expired_and_reuses_when_fresh(self, mock_session):
        mock_session.return_value.post.side_effect = [
            _token_response(payload={"access_token": "first", "expires_in": 3600}),
            _token_response(payload={"access_token": "second", "expires_in": 3600}),
        ]
        auth = OAuth2Auth(token_url="https://auth.example.com/token", client_id="cid", client_secret="cs")
        assert _apply_auth(auth) == "Bearer first"
        # Force the cached token past expiry — the next request must re-mint.
        auth.token_expiry = datetime.now(UTC) - timedelta(seconds=1)
        assert _apply_auth(auth) == "Bearer second"
        # Now fresh again — a third request reuses without a third mint.
        assert _apply_auth(auth) == "Bearer second"
        assert mock_session.return_value.post.call_count == 2

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_expiry_buffer_remints_before_declared_expiry(self, mock_session):
        mock_session.return_value.post.side_effect = [
            _token_response(payload={"access_token": "first", "expires_in": 3600}),
            _token_response(payload={"access_token": "second", "expires_in": 3600}),
        ]
        auth = OAuth2Auth(token_url="https://auth.example.com/token", client_id="cid", client_secret="cs")
        assert _apply_auth(auth) == "Bearer first"
        # A long-lived (1h) token now 30s from expiry — inside the 60s refresh buffer, so re-mint.
        # _minted_at is set alongside token_expiry so the buffer isn't clamped down to a tiny TTL.
        auth._minted_at = datetime.now(UTC) - timedelta(hours=1)
        auth.token_expiry = datetime.now(UTC) + timedelta(seconds=30)
        assert _apply_auth(auth) == "Bearer second"

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_short_lived_token_is_not_reminted_every_request(self, mock_session):
        # A genuinely short-lived token (TTL <= the 60s buffer) must not read as expired the
        # instant it's minted — the buffer is capped at half the lifetime, so it stays usable.
        mock_session.return_value.post.return_value = _token_response(
            payload={"access_token": "short", "expires_in": 20}
        )
        auth = OAuth2Auth(token_url="https://auth.example.com/token", client_id="cid", client_secret="cs")
        assert _apply_auth(auth) == "Bearer short"
        # Immediately after minting it's still fresh (not re-minted) despite TTL < buffer.
        assert _apply_auth(auth) == "Bearer short"
        assert mock_session.return_value.post.call_count == 1

    def test_secret_values_includes_minted_token(self):
        auth = OAuth2Auth(client_secret="csecret", refresh_token="refresh-x")
        # Before minting: the static secrets only.
        assert set(auth.secret_values()) == {"csecret", "refresh-x"}
        # After minting, the dynamically-obtained access token joins the redaction set —
        # otherwise it could leak from an error URL or sample that surfaces later.
        auth.token = "minted-token"
        assert set(auth.secret_values()) == {"csecret", "refresh-x", "minted-token"}

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_token_exchange_disables_capture_and_redacts_secret(self, mock_session):
        mock_session.return_value.post.return_value = _token_response(payload={"access_token": "t", "expires_in": 60})
        auth = OAuth2Auth(token_url="https://a/t", client_id="cid", client_secret="topsecret")
        _apply_auth(auth)
        kwargs = mock_session.call_args.kwargs
        # The response body carries the minted token, which the name-based scrubbers can't
        # recognise — the exchange must be excluded from sample capture and pinned no-redirect.
        assert kwargs["capture"] is False
        assert kwargs["allow_redirects"] is False
        assert "topsecret" in kwargs["redact_values"]

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_basic_client_auth_method_uses_http_basic_not_body(self, mock_session):
        mock_session.return_value.post.return_value = _token_response(payload={"access_token": "t", "expires_in": 60})
        auth = OAuth2Auth(token_url="https://a/t", client_id="cid", client_secret="cs", client_auth_method="basic")
        _apply_auth(auth)
        call = mock_session.return_value.post.call_args
        assert call.kwargs["auth"] == ("cid", "cs")
        # In basic mode the credentials must NOT also be duplicated into the form body.
        assert "client_secret" not in call.kwargs["data"]
        assert "client_id" not in call.kwargs["data"]

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_non_standard_token_field_scopes_and_extra_params(self, mock_session):
        mock_session.return_value.post.return_value = _token_response(payload={"my_token": "abc", "expires_in": 60})
        auth = OAuth2Auth(
            token_url="https://a/t",
            client_id="cid",
            client_secret="cs",
            scopes="read write",
            access_token_name="my_token",
            extra_token_request_params={"audience": "https://api.example.com"},
        )
        # access_token_name reads the token from a non-standard response field.
        assert _apply_auth(auth) == "Bearer abc"
        body = mock_session.return_value.post.call_args.kwargs["data"]
        # scopes stay a single space-separated string; extra params reach the body (the Auth0 case).
        assert body["scope"] == "read write"
        assert body["audience"] == "https://api.example.com"

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_absolute_datetime_expiry_field(self, mock_session):
        # The Square case: the provider returns an absolute `expires_at` datetime, not seconds.
        mock_session.return_value.post.return_value = _token_response(
            payload={"access_token": "t", "expires_at": "2999-01-01T00:00:00Z"}
        )
        auth = OAuth2Auth(
            token_url="https://a/t",
            client_id="cid",
            client_secret="cs",
            expires_in_name="expires_at",
            expiry_date_format="%Y-%m-%dT%H:%M:%SZ",
        )
        _apply_auth(auth)
        assert auth.token_expiry == datetime(2999, 1, 1, tzinfo=UTC)

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_token_request_headers_forwarded(self, mock_session):
        mock_session.return_value.post.return_value = _token_response(payload={"access_token": "t", "expires_in": 60})
        auth = OAuth2Auth(
            token_url="https://a/t",
            client_id="cid",
            client_secret="cs",
            token_request_headers={"X-Tenant": "acme"},
        )
        _apply_auth(auth)
        assert mock_session.return_value.post.call_args.kwargs["headers"] == {"X-Tenant": "acme"}

    @parameterized.expand(
        [
            ("invalid_client_401", 401, "invalid_client", True),
            ("invalid_grant_400", 400, "invalid_grant", True),
            # An unfollowed 3xx means token_url is misconfigured — permanent, not a transient retry.
            ("redirect_302", 302, None, True),
            ("rate_limited_429", 429, "slow_down", False),
            ("server_error_503", 503, None, False),
        ]
    )
    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_token_error_classification(self, _name, status_code, error_code, expected_permanent, mock_session):
        payload = {"error": error_code} if error_code else {}
        response = _token_response(status_code=status_code, payload=payload)
        response.text = "RAW BODY THAT MIGHT CONTAIN topsecret"
        mock_session.return_value.post.return_value = response
        auth = OAuth2Auth(token_url="https://a/t", client_id="cid", client_secret="topsecret")
        with self.assertRaises(OAuth2AuthRequestError) as ctx:
            auth._obtain_token()
        assert ctx.exception.is_permanent is expected_permanent
        if error_code:
            assert error_code in str(ctx.exception)
        # The raw body (and any secret it might echo) is never surfaced in the error.
        assert "topsecret" not in str(ctx.exception)
        assert "RAW BODY" not in str(ctx.exception)

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_missing_access_token_field_raises_permanent(self, mock_session):
        mock_session.return_value.post.return_value = _token_response(payload={"expires_in": 60})
        auth = OAuth2Auth(token_url="https://a/t", client_id="cid", client_secret="cs")
        with self.assertRaises(OAuth2AuthRequestError) as ctx:
            auth._obtain_token()
        assert ctx.exception.is_permanent

    def test_refresh_grant_without_refresh_token_raises(self):
        auth = OAuth2Auth(token_url="https://a/t", client_id="cid", client_secret="cs", grant_type="refresh_token")
        with self.assertRaises(OAuth2AuthRequestError):
            auth._obtain_token()
