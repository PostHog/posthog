import json
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    _TOKEN_CONNECT_TIMEOUT,
    _TOKEN_READ_TIMEOUT,
    OAuth2Auth,
    OAuth2AuthRequestError,
)

AUTH_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth"


def _token_response(status_code: int = 200, payload: Optional[dict[str, Any]] = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    # The exchange reads a capped `response.raw.read(...)` then json.loads — seed the raw body to match.
    response.raw.read.return_value = json.dumps(payload if payload is not None else {}).encode()
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
        # No refresh_token in the response → nothing to write back.
        assert auth.rotated_refresh_token is None

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_externally_managed_token_never_mints_even_when_expired(self, mock_session):
        # A single-use refresh token rotates only once, so an integration-backed source seeds a static
        # bearer with manages_own_token=False: the engine must never re-mint. Even with no known expiry
        # (so _is_token_expired() reads True), __call__ sends the seeded token as-is (the resource server
        # 401s — a retryable failure whose retry re-mints up front through the row) instead of consuming
        # and losing the rotation.
        auth = OAuth2Auth(
            token_url="https://auth.example.com/token",
            client_id="cid",
            client_secret="cs",
            grant_type="refresh_token",
            refresh_token="orig-RT",
            access_token="seeded-AT",
            manages_own_token=False,
        )
        assert _apply_auth(auth) == "Bearer seeded-AT"
        mock_session.return_value.post.assert_not_called()

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
        # returns a new one — it must keep minting with the original this run. Mutating it here
        # would silently diverge from the persisted value.
        assert auth.refresh_token == "refresh-orig"
        # The rotated token is captured separately so a caller holding a DB row can persist it for
        # the next sync (the rotating-provider writeback this enables — e.g. Calendly).
        assert auth.rotated_refresh_token == "refresh-rotated"

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
    def test_extra_params_cannot_override_required_token_params(self, mock_session):
        # extra_token_request_params is for provider-specific knobs, not for clobbering the grant_type /
        # client_id / refresh_token this engine derives from its config (which would let a manifest smuggle
        # a different grant past validation). Non-conflicting extras still pass through.
        mock_session.return_value.post.return_value = _token_response(payload={"access_token": "t", "expires_in": 60})
        auth = OAuth2Auth(
            token_url="https://a/t",
            client_id="real-cid",
            client_secret="cs",
            grant_type="client_credentials",
            extra_token_request_params={"grant_type": "authorization_code", "client_id": "attacker", "audience": "aud"},
        )

        _apply_auth(auth)

        body = mock_session.return_value.post.call_args.kwargs["data"]
        assert body["grant_type"] == "client_credentials"
        assert body["client_id"] == "real-cid"
        assert body["audience"] == "aud"

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
    def test_malformed_absolute_expiry_falls_back_to_default_ttl(self, mock_session):
        # A configured expiry_date_format with an unparseable value must not propagate strptime's
        # ValueError (which would fail the whole sync) — it falls back to the conservative default.
        mock_session.return_value.post.return_value = _token_response(
            payload={"access_token": "t", "expires_at": "not-a-date"}
        )
        auth = OAuth2Auth(
            token_url="https://a/t",
            client_id="cid",
            client_secret="cs",
            expires_in_name="expires_at",
            expiry_date_format="%Y-%m-%dT%H:%M:%SZ",
        )
        _apply_auth(auth)
        assert auth.token_expiry is not None
        assert auth.token_expiry > datetime.now(UTC) + timedelta(minutes=50)

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_numeric_string_expires_in(self, mock_session):
        # Some providers send expires_in as a JSON string; the digit-string branch parses it
        # (7200s here, distinguishable from the 1h default that an unparsed value would yield).
        mock_session.return_value.post.return_value = _token_response(
            payload={"access_token": "t", "expires_in": "7200"}
        )
        auth = OAuth2Auth(token_url="https://a/t", client_id="cid", client_secret="cs")
        _apply_auth(auth)
        assert auth.token_expiry is not None
        assert auth.token_expiry > datetime.now(UTC) + timedelta(minutes=100)

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_missing_expiry_field_uses_default_ttl(self, mock_session):
        # No expiry hint at all → the conservative 1h default so a long sync still re-mints.
        mock_session.return_value.post.return_value = _token_response(payload={"access_token": "t"})
        auth = OAuth2Auth(token_url="https://a/t", client_id="cid", client_secret="cs")
        _apply_auth(auth)
        now = datetime.now(UTC)
        assert auth.token_expiry is not None
        assert now + timedelta(minutes=50) < auth.token_expiry < now + timedelta(minutes=70)

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

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_obtain_token_default_and_explicit_timeout(self, mock_session):
        # The sync path uses the generous default; the create-time pre-mint passes a tighter budget
        # so a stalled token endpoint can't pin the inline API request thread for the full read.
        mock_session.return_value.post.return_value = _token_response(payload={"access_token": "t", "expires_in": 60})
        auth = OAuth2Auth(token_url="https://a/t", client_id="cid", client_secret="cs")
        _apply_auth(auth)
        assert mock_session.return_value.post.call_args.kwargs["timeout"] == (
            _TOKEN_CONNECT_TIMEOUT,
            _TOKEN_READ_TIMEOUT,
        )
        auth._obtain_token(timeout=(3, 7))
        assert mock_session.return_value.post.call_args.kwargs["timeout"] == (3, 7)

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

    @parameterized.expand(
        [
            # The token endpoint returned a 2xx but the body isn't JSON the client can parse — a
            # config error against the wrong URL, not something a retry fixes.
            ("non_json_body", "non_json", None),
            # A 2xx whose top-level JSON is a list/array rather than the expected object — same.
            ("array_body", None, [{"access_token": "t"}]),
        ]
    )
    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_malformed_token_response_raises_permanent(self, _name, json_side_effect, json_return, mock_session):
        response = _token_response(status_code=200)
        if json_side_effect == "non_json":
            response.raw.read.return_value = b"<html>not json</html>"
        else:
            response.raw.read.return_value = json.dumps(json_return).encode()
        mock_session.return_value.post.return_value = response
        auth = OAuth2Auth(token_url="https://a/t", client_id="cid", client_secret="cs")
        with self.assertRaises(OAuth2AuthRequestError) as ctx:
            auth._obtain_token()
        assert ctx.exception.is_permanent is True

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_oversized_token_response_raises_permanent(self, mock_session):
        # A hostile token_url returning a huge 2xx body must not be buffered whole (worker OOM); the read is
        # capped and an oversized body fails permanently.
        response = _token_response(status_code=200)
        response.raw.read.return_value = b"x" * (256 * 1024 + 1)
        mock_session.return_value.post.return_value = response
        auth = OAuth2Auth(token_url="https://a/t", client_id="cid", client_secret="cs")

        with self.assertRaises(OAuth2AuthRequestError) as ctx:
            auth._obtain_token()

        assert ctx.exception.is_permanent is True
        assert "oversized" in str(ctx.exception)

    def test_refresh_grant_without_refresh_token_raises(self):
        auth = OAuth2Auth(token_url="https://a/t", client_id="cid", client_secret="cs", grant_type="refresh_token")
        with self.assertRaises(OAuth2AuthRequestError):
            auth._obtain_token()
