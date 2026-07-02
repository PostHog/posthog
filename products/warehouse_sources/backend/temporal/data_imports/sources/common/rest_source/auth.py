import json
from base64 import b64encode
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Optional

from requests import PreparedRequest, Response
from requests.auth import AuthBase
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session

TApiKeyLocation = Literal["header", "query", "param", "cookie"]
OAuth2GrantType = Literal["client_credentials", "refresh_token"]
OAuth2ClientAuthMethod = Literal["body", "basic"]


class AuthConfigBase(AuthBase):
    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        return request

    def __bool__(self) -> bool:
        return True

    def secret_values(self) -> tuple[str, ...]:
        """Credential strings this auth carries, for log redaction.

        The tracked HTTP transport masks these wherever they appear in logged
        URLs, headers, and sampled bodies — so a credential injected under a
        param/header name the denylist scrubber can't know in advance (e.g. an
        API key in a query param) is still redacted. Each subclass declares its
        own secret so the list can't drift from the field that holds it.
        """
        return ()


class BearerTokenAuth(AuthConfigBase):
    def __init__(self, token: Optional[str] = None) -> None:
        self.token = token

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        request.headers["Authorization"] = f"Bearer {self.token}"
        return request

    def secret_values(self) -> tuple[str, ...]:
        return (self.token,) if self.token else ()


class APIKeyAuth(AuthConfigBase):
    def __init__(
        self,
        api_key: Optional[str] = None,
        name: str = "Authorization",
        location: TApiKeyLocation = "header",
    ) -> None:
        self.api_key = api_key
        self.name = name
        self.location = location

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        if self.location == "header":
            request.headers[self.name] = self.api_key or ""
        elif self.location in ("query", "param"):
            request.prepare_url(request.url, {self.name: self.api_key})
        elif self.location == "cookie":
            request.prepare_cookies({self.name: self.api_key or ""})
        return request

    def secret_values(self) -> tuple[str, ...]:
        return (self.api_key,) if self.api_key else ()


class HttpBasicAuth(AuthConfigBase):
    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        self.username = username
        self.password = password

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        encoded = b64encode(f"{self.username}:{self.password}".encode()).decode()
        request.headers["Authorization"] = f"Basic {encoded}"
        return request

    def secret_values(self) -> tuple[str, ...]:
        return (self.password,) if self.password else ()


# Re-mint the access token this many seconds before its declared expiry, so a
# token that's still valid at the check isn't rejected mid-flight by the upstream.
# Mirrors Airbyte's OAuthAuthenticator and SalesforceAuth's own clock skew handling.
_TOKEN_EXPIRY_BUFFER = timedelta(seconds=60)
# When the token response declares no usable expiry, assume a conservative lifetime
# so a long-running sync still re-mints rather than caching a dead token forever.
_DEFAULT_TOKEN_TTL = timedelta(hours=1)
# Token exchanges run on the worker (sync) or the API request thread (create-time
# probe), so keep them tightly bounded — a stalled token endpoint must not hang either.
_TOKEN_CONNECT_TIMEOUT = 10
_TOKEN_READ_TIMEOUT = 30
# The customer configures token_url, so a hostile one could return an unbounded 2xx body; the exchange
# runs on shared workers, so cap what we buffer before parsing. A token response is a few KB — 256 KiB is
# generous headroom without risking a worker OOM.
_MAX_TOKEN_RESPONSE_BYTES = 256 * 1024


# Stable marker appended to every permanent OAuth2 token error message. At sync time the
# pipeline classifies non-retryable errors by substring-matching the stringified exception
# (see CustomSource.get_non_retryable_errors), and the permanent cases here have no single
# shared phrase to match on — they range over OAuth error codes (unauthorized_client,
# invalid_scope …), bare "HTTP 3xx from the OAuth2 token endpoint" with no code at all, and
# malformed-response messages, while transient 429/5xx token errors share the very same
# "from the OAuth2 token endpoint" phrasing. This marker is the one stable substring that is
# present on permanent token failures and absent on retryable ones.
OAUTH2_PERMANENT_ERROR_MARKER = "[oauth2_token_config_error]"


class OAuth2AuthRequestError(Exception):
    """A token exchange against the customer's OAuth2 token endpoint failed.

    Carries only the provider's standard ``error`` / ``error_description`` — never
    the raw response body, which could echo the posted ``client_secret`` back into
    a user-facing error or log. ``is_permanent`` distinguishes a config error that
    retrying can't fix (``invalid_client`` / ``invalid_grant`` and other 4xx) from
    a transient failure (429 / 5xx) the caller may retry.

    When ``is_permanent`` is set, the message embeds :data:`OAUTH2_PERMANENT_ERROR_MARKER`
    so the sync-time non-retryable classifier can reliably recognise every permanent case
    (not just the handful that carry a known OAuth error code) by a single stable substring.
    """

    def __init__(self, message: str, *, error_code: Optional[str] = None, is_permanent: bool = False) -> None:
        if is_permanent and OAUTH2_PERMANENT_ERROR_MARKER not in message:
            message = f"{message} {OAUTH2_PERMANENT_ERROR_MARKER}"
        super().__init__(message)
        self.error_code = error_code
        self.is_permanent = is_permanent


class OAuth2Auth(BearerTokenAuth):
    """OAuth2 auth for customer-owned clients (``client_credentials`` / ``refresh_token``).

    The customer brings their own OAuth2 client (``client_id`` / ``client_secret`` /
    ``token_url``); the worker mints a short-lived access token at request time, caches
    it in memory for the run, and re-mints on expiry — the same lazy, in-process
    refresh as :class:`SalesforceAuth`, but config-driven (no PostHog-registered app
    and no interactive consent flow). ``authorization_code`` is out of scope and is
    rejected at manifest validation, so only the two non-interactive grants reach here.
    """

    def __init__(
        self,
        token_url: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        grant_type: OAuth2GrantType = "client_credentials",
        scopes: Optional[str] = None,
        refresh_token: Optional[str] = None,
        access_token: Optional[str] = None,
        # --- Extensibility knobs (all optional, all non-secret) for the provider long tail. ---
        access_token_name: str = "access_token",
        expires_in_name: str = "expires_in",
        expiry_date_format: Optional[str] = None,
        extra_token_request_params: Optional[dict[str, str]] = None,
        token_request_headers: Optional[dict[str, str]] = None,
        client_auth_method: OAuth2ClientAuthMethod = "body",
        manages_own_token: bool = True,
    ) -> None:
        super().__init__(token=access_token)
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.grant_type = grant_type
        self.scopes = scopes
        self.refresh_token = refresh_token
        self.access_token_name = access_token_name
        self.expires_in_name = expires_in_name
        self.expiry_date_format = expiry_date_format
        self.extra_token_request_params = extra_token_request_params
        self.token_request_headers = token_request_headers
        self.client_auth_method = client_auth_method
        # False for an integration-backed source: it mints + persists its token up front (under a row
        # lock) and hands this auth a ready bearer, so the engine must never mint. A mid-sync re-mint
        # would consume a single-use refresh token whose rotation this in-memory auth can't persist,
        # permanently orphaning the integration. See __call__.
        self.manages_own_token = manages_own_token
        # A rotating provider returns a fresh single-use refresh token alongside each access token;
        # captured here (never overwriting self.refresh_token, which must keep minting this run) so a
        # caller holding a DB row can persist it for the next sync. None until a rotation is seen.
        self.rotated_refresh_token: Optional[str] = None
        # None => mint on the first request. A pre-supplied access_token (rare; never set for custom
        # sources today) has no known expiry, so it too re-mints first.
        self.token_expiry: Optional[datetime] = None
        # When the current token was minted — used to cap the refresh buffer at half the
        # token's lifetime so a very short-lived token isn't treated as expired the instant
        # it's minted (which would re-mint on every request).
        self._minted_at: Optional[datetime] = None

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        # An externally managed token (manages_own_token=False, the integration path) was minted +
        # persisted up front, so never mint here. Send the token; if it has expired the resource server
        # returns a 401 — a retryable failure whose retry re-mints up front through the row, so a
        # single-use refresh token is never consumed inside the engine and can't be lost.
        if self.manages_own_token and (self.token is None or self._is_token_expired()):
            self._obtain_token()
        # The minted token must stay on the `Authorization` header. At sync time the tracked
        # session fixes its value-based redaction set at construction — before this lazy mint —
        # so the minted token isn't in it; it's redacted only by the header-name denylist. Moving
        # it to a custom-named header would silently lose that backstop (see secret_values()).
        request.headers["Authorization"] = f"Bearer {self.token}"
        return request

    def _is_token_expired(self) -> bool:
        if self.token_expiry is None:
            return True
        # Refresh slightly before the declared expiry to avoid a mid-flight rejection, but cap
        # the buffer at half the token's lifetime: a token whose whole TTL is <= the buffer would
        # otherwise read as already-expired the moment it's minted, re-minting on every request.
        lifetime = self.token_expiry - self._minted_at if self._minted_at else _TOKEN_EXPIRY_BUFFER * 2
        buffer = min(_TOKEN_EXPIRY_BUFFER, lifetime / 2)
        return datetime.now(UTC) >= (self.token_expiry - buffer)

    def secret_values(self) -> tuple[str, ...]:
        # MUST override the base (which redacts only the access token): the
        # client_secret and refresh_token are equally sensitive, and the
        # dynamically-minted access token is included so it's masked wherever it
        # surfaces (an error URL, a sampled body) — the redaction contract.
        return tuple(value for value in (self.client_secret, self.token, self.refresh_token) if value)

    def _build_token_request_body(self) -> dict[str, str]:
        # Seed with the caller's extras first so the required OAuth2 params set below always win. The extras
        # are for provider-specific knobs (e.g. an `audience`); they must not be able to override the
        # grant_type, client_id/secret, or refresh_token this auth engine derives from its config.
        body: dict[str, str] = dict(self.extra_token_request_params or {})
        body["grant_type"] = self.grant_type
        if self.grant_type == "refresh_token":
            if not self.refresh_token:
                raise OAuth2AuthRequestError(
                    "A refresh_token is required for the refresh_token grant", is_permanent=True
                )
            body["refresh_token"] = self.refresh_token
        if self.scopes:
            body["scope"] = self.scopes
        # RFC 6749 §2.3.1 permits the client credentials in the body or as HTTP Basic.
        # In "body" mode they travel in the form body; "basic" mode sends them in the
        # Authorization header instead (see _obtain_token).
        if self.client_auth_method == "body":
            if self.client_id:
                body["client_id"] = self.client_id
            if self.client_secret:
                body["client_secret"] = self.client_secret
        return body

    def _obtain_token(self, timeout: Optional[tuple[float, float]] = None) -> None:
        if not self.token_url:
            raise OAuth2AuthRequestError("A token_url is required to obtain an OAuth2 access token", is_permanent=True)
        body = self._build_token_request_body()
        basic_auth = (self.client_id or "", self.client_secret or "") if self.client_auth_method == "basic" else None
        # capture=False: the response body carries the minted access_token, which the
        # name-based sample scrubbers can't recognise — keep the exchange out of HTTP
        # samples entirely. allow_redirects=False pins the credential to the validated
        # token host (a 3xx must not bounce the client_secret elsewhere). retry=Retry(0)
        # so 429/5xx aren't silently retried here — we classify and let the caller decide.
        session = make_tracked_session(
            redact_values=self.secret_values(),
            allow_redirects=False,
            capture=False,
            retry=Retry(total=0),
        )
        # `timeout` lets the create-time pre-mint pass a tighter budget than the sync default:
        # the pre-mint runs inline on the API request thread, so it must stay within the same
        # bound as the data probe rather than blocking for the full sync-time read timeout.
        # stream=True so the body isn't buffered until we read it under a cap (see _read_capped_token_payload).
        response = session.post(
            self.token_url,
            data=body,
            auth=basic_auth,
            headers=self.token_request_headers or None,
            timeout=timeout or (_TOKEN_CONNECT_TIMEOUT, _TOKEN_READ_TIMEOUT),
            stream=True,
        )
        payload = _read_capped_token_payload(response)
        if 200 <= response.status_code < 300:
            self._apply_token_response(payload)
            return
        error_code, description = _extract_token_error(payload)
        message = _format_token_error(response.status_code, error_code, description)
        # A 4xx other than 429 (invalid_client / invalid_grant / unauthorized_client …) is a
        # permanent config error; a 3xx is too — the session pins allow_redirects=False, so an
        # unfollowed redirect means token_url is misconfigured and retrying can't fix it. Only
        # 429 and 5xx are transient and worth a caller/Temporal retry.
        is_permanent = 300 <= response.status_code < 500 and response.status_code != 429
        raise OAuth2AuthRequestError(message, error_code=error_code, is_permanent=is_permanent)

    def _apply_token_response(self, payload: Optional[dict[str, Any]]) -> None:
        if payload is None:
            raise OAuth2AuthRequestError(
                "The OAuth2 token endpoint returned a non-JSON or unexpected response", is_permanent=True
            )
        token = payload.get(self.access_token_name)
        if not isinstance(token, str) or not token:
            raise OAuth2AuthRequestError(
                f"The OAuth2 token response did not contain a string {self.access_token_name!r} field",
                is_permanent=True,
            )
        self.token = token
        self._minted_at = datetime.now(UTC)
        self.token_expiry = self._parse_token_expiry(payload)
        # Capture a rotated refresh token without mutating self.refresh_token: a single-use grant
        # must keep using the original token to mint within this run, while a caller with a DB row
        # persists the rotated one for the next sync. Only a non-empty string counts as a rotation.
        rotated = payload.get("refresh_token")
        if isinstance(rotated, str) and rotated:
            self.rotated_refresh_token = rotated

    def _parse_token_expiry(self, payload: dict[str, Any]) -> datetime:
        now = datetime.now(UTC)
        raw = payload.get(self.expires_in_name)
        if self.expiry_date_format and isinstance(raw, str):
            # The provider returns an absolute datetime string (e.g. Square's expires_at)
            # rather than a TTL in seconds; parse it with the declared format.
            try:
                parsed = datetime.strptime(raw, self.expiry_date_format)
            except ValueError:
                return now + _DEFAULT_TOKEN_TTL
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        if isinstance(raw, bool):
            # bool is an int subclass — a stray `true` is not a TTL.
            return now + _DEFAULT_TOKEN_TTL
        if isinstance(raw, (int, float)):
            return now + timedelta(seconds=int(raw))
        if isinstance(raw, str) and raw.strip().isdigit():
            return now + timedelta(seconds=int(raw.strip()))
        # No usable expiry hint — assume a conservative TTL so a long sync still re-mints.
        return now + _DEFAULT_TOKEN_TTL


def _read_capped_token_payload(response: Response) -> Optional[dict[str, Any]]:
    """Read the token response body under a size cap, then JSON-parse it.

    The request is made with ``stream=True``, so the body isn't materialised until this read. We read one
    byte past the cap to detect an oversized body without buffering the whole thing — a hostile ``token_url``
    (the customer configures it) could otherwise return an unbounded 2xx body and OOM a shared worker.
    Returns ``None`` for a body that isn't a JSON object; callers decide whether that's an error.
    """
    raw = response.raw.read(_MAX_TOKEN_RESPONSE_BYTES + 1, decode_content=True)
    if len(raw) > _MAX_TOKEN_RESPONSE_BYTES:
        raise OAuth2AuthRequestError("The OAuth2 token endpoint returned an oversized response", is_permanent=True)
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _extract_token_error(payload: Optional[dict[str, Any]]) -> tuple[Optional[str], str]:
    """Pull the standard OAuth2 ``error`` / ``error_description`` from a failed token response.

    Reads only those two fields — never the raw body, which could echo the posted
    ``client_secret`` back. Returns ``(None, "")`` for a non-JSON or unexpected body.
    """
    if payload is None:
        return None, ""
    error_code = payload.get("error")
    description = payload.get("error_description")
    return (
        error_code if isinstance(error_code, str) else None,
        description if isinstance(description, str) else "",
    )


def _format_token_error(status_code: int, error_code: Optional[str], description: str) -> str:
    parts = [f"HTTP {status_code} from the OAuth2 token endpoint"]
    if error_code:
        parts.append(error_code)
    if description:
        parts.append(description)
    return ": ".join(parts)


def strip_oauth2_permanent_marker(text: str) -> str:
    """Drop the internal permanent-error marker from a message before showing it to a user.

    :data:`OAUTH2_PERMANENT_ERROR_MARKER` is a sync-time classifier hint, not user-facing
    copy — strip it (and the space that precedes it) wherever a token-error message is
    surfaced at create or preview time.
    """
    return text.replace(f" {OAUTH2_PERMANENT_ERROR_MARKER}", "").replace(OAUTH2_PERMANENT_ERROR_MARKER, "")


def auth_secret_values(auth: Optional[AuthBase]) -> tuple[str, ...]:
    """Secret credential strings carried by an auth object, for log redaction.

    Delegates to :meth:`AuthConfigBase.secret_values` so the knowledge of which
    field is secret lives on each auth class. Returns ``()`` for ``None`` or any
    auth that isn't an :class:`AuthConfigBase`.
    """
    return auth.secret_values() if isinstance(auth, AuthConfigBase) else ()
