import time
import hashlib
import threading
import dataclasses
from typing import Any, Optional

from requests import PreparedRequest, Response

from products.warehouse_sources.sources.sdk import (
    AuthConfigBase,
    OffsetPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    frozen,
    make_tracked_session,
    raise_for_retryable_status,
    rest_api_resource,
    vendor_retry,
)
from products.warehouse_sources.sources.zoho_desk._config import ZohoDeskSourceConfig
from products.warehouse_sources.sources.zoho_desk.settings import ZOHO_DESK_ENDPOINTS, ZohoDeskEndpointConfig

API_PATH = "/api/v1"
TOKEN_PATH = "/oauth/v2/token"
AUTH_SCHEME = "Zoho-oauthtoken"
TOKEN_TIMEOUT_SECONDS = 30
DEFAULT_TOKEN_LIFETIME_SECONDS = 60 * 60
TOKEN_REFRESH_MARGIN_SECONDS = 5 * 60


@frozen
class RegionHosts:
    accounts_host: str
    desk_host: str


ZOHO_DESK_REGIONS: dict[str, RegionHosts] = {
    "us": RegionHosts(accounts_host="https://accounts.zoho.com", desk_host="https://desk.zoho.com"),
    "eu": RegionHosts(accounts_host="https://accounts.zoho.eu", desk_host="https://desk.zoho.eu"),
    "uk": RegionHosts(accounts_host="https://accounts.zoho.uk", desk_host="https://desk.zoho.uk"),
    "in": RegionHosts(accounts_host="https://accounts.zoho.in", desk_host="https://desk.zoho.in"),
    "au": RegionHosts(accounts_host="https://accounts.zoho.com.au", desk_host="https://desk.zoho.com.au"),
    "jp": RegionHosts(accounts_host="https://accounts.zoho.jp", desk_host="https://desk.zoho.jp"),
    "ca": RegionHosts(accounts_host="https://accounts.zohocloud.ca", desk_host="https://desk.zohocloud.ca"),
    "sa": RegionHosts(accounts_host="https://accounts.zoho.sa", desk_host="https://desk.zoho.sa"),
    "sg": RegionHosts(accounts_host="https://accounts.zoho.sg", desk_host="https://desk.zoho.sg"),
    "ae": RegionHosts(accounts_host="https://accounts.zoho.ae", desk_host="https://desk.zoho.ae"),
    "cn": RegionHosts(accounts_host="https://accounts.zoho.com.cn", desk_host="https://desk.zoho.com.cn"),
}

REFRESH_TOKEN_REJECTED_MESSAGE = (
    "Zoho Desk rejected your refresh token. Exchange a new code from your self client's Generate Code tab "
    "for a refresh token, then reconnect."
)
CLIENT_REJECTED_MESSAGE = (
    "Zoho Desk doesn't recognize this client in the data center you picked. Check the client ID and secret, "
    "and pick the data center your Zoho account uses."
)
CLIENT_SECRET_REJECTED_MESSAGE = (
    "Zoho Desk rejected your client secret. Copy it again from your self client, then reconnect."
)
# The error codes that mean the stored credentials are wrong. `invalid_client_secret` comes first
# because error patterns match as substrings.
TOKEN_ERROR_MESSAGES = {
    "invalid_client_secret": CLIENT_SECRET_REJECTED_MESSAGE,
    "invalid_client": CLIENT_REJECTED_MESSAGE,
    "invalid_code": REFRESH_TOKEN_REJECTED_MESSAGE,
}
TOKEN_REFRESH_FAILED_PREFIX = "Zoho Desk token refresh failed"


class ZohoDeskAuthError(Exception):
    """Zoho rejected the client or the refresh token, so a retry with the same credentials fails too."""

    def __init__(self, error_code: str) -> None:
        super().__init__(f"{TOKEN_REFRESH_FAILED_PREFIX}: {error_code}")
        self.error_code = error_code

    @property
    def user_message(self) -> str:
        return TOKEN_ERROR_MESSAGES.get(self.error_code, REFRESH_TOKEN_REJECTED_MESSAGE)


class ZohoDeskTokenUnavailableError(Exception):
    """The token exchange returned no access token, and not because of a known credential error.

    Zoho limits how many access tokens one refresh token can mint in a short period. This error
    stays retryable so that a later attempt can mint one.
    """


@frozen
class ZohoDeskResumeConfig:
    next_index: int
    last_id: Optional[str] = None


@frozen
class _AccessToken:
    value: str = dataclasses.field(repr=False)
    deadline: float


class _AccessTokenCache:
    """Access tokens that the syncs in one worker process share, one for each set of credentials.

    Zoho limits how many access tokens one refresh token can mint in a short period. Each table of
    a source syncs on its own, so without sharing, a source with many tables asks for more tokens
    than Zoho gives. The lock for a set of credentials makes concurrent syncs wait for one exchange.
    """

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._tokens: dict[str, _AccessToken] = {}

    def lock(self, key: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())

    def get(self, key: str) -> Optional[_AccessToken]:
        return self._tokens.get(key)

    def put(self, key: str, token: _AccessToken) -> None:
        self._tokens[key] = token

    def clear(self) -> None:
        with self._guard:
            self._tokens.clear()
            self._locks.clear()


ACCESS_TOKENS = _AccessTokenCache()


def resolve_hosts(region: str) -> RegionHosts:
    hosts = ZOHO_DESK_REGIONS.get(region)
    if hosts is None:
        raise ValueError(f"Invalid Zoho Desk region: {region}")
    return hosts


def _token_lifetime_seconds(expires_in: Any) -> float:
    if isinstance(expires_in, bool) or not isinstance(expires_in, int | float) or expires_in <= 0:
        return DEFAULT_TOKEN_LIFETIME_SECONDS
    return float(expires_in)


class ZohoDeskAuth(AuthConfigBase):
    """Exchanges the refresh token for an access token that lasts until shortly before it expires.

    The framework `oauth2` auth treats every 4xx from the token endpoint as a permanent credential
    error. Zoho answers a wrong credential with HTTP 200 and an `error` key, and it also throttles
    token requests, so this class reads the `error` key and fails permanently only for the codes
    that name a wrong credential.
    """

    def __init__(self, accounts_host: str, client_id: str, client_secret: str, refresh_token: str) -> None:
        self._token_url = f"{accounts_host}{TOKEN_PATH}"
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._cache_key = hashlib.sha256("\0".join((self._token_url, client_id, refresh_token)).encode()).hexdigest()

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        request.headers["Authorization"] = self._authorization()
        request.register_hook("response", self._resend_with_new_token)
        return request

    def secret_values(self) -> tuple[str, ...]:
        cached = ACCESS_TOKENS.get(self._cache_key)
        token = cached.value if cached else None
        return tuple(value for value in (self._client_secret, self._refresh_token, token) if value)

    def access_token(self, rejected: Optional[str] = None) -> str:
        """The shared access token. `rejected` is a token that Zoho answered with a 401: it is
        replaced unless another sync replaced it first."""
        with ACCESS_TOKENS.lock(self._cache_key):
            cached = ACCESS_TOKENS.get(self._cache_key)
            if (
                cached is None
                or cached.value == rejected
                or time.monotonic() >= cached.deadline - TOKEN_REFRESH_MARGIN_SECONDS
            ):
                cached = self._mint()
                ACCESS_TOKENS.put(self._cache_key, cached)
            return cached.value

    def _authorization(self, rejected: Optional[str] = None) -> str:
        return f"{AUTH_SCHEME} {self.access_token(rejected)}"

    def _resend_with_new_token(self, response: Response, **send_kwargs: Any) -> Response:
        """Send a request that got a 401 once more, with a newly minted token.

        Zoho keeps a limited number of access tokens alive for each refresh token, so a token can
        stop working before it expires, when other workers mint theirs. The adapter sends the copy
        directly and does not run this hook again, so a second 401 goes back to the caller as a
        real credential failure. The client does not follow redirects, so the request that reaches
        this hook always went to the Desk host.
        """
        if response.status_code != 401:
            return response
        # Read the body so that the connection goes back to the pool before the second request.
        _ = response.content
        rejected = str(response.request.headers.get("Authorization", "")).removeprefix(f"{AUTH_SCHEME} ")
        resent = response.request.copy()
        resent.headers["Authorization"] = self._authorization(rejected)
        second_response: Response = response.connection.send(resent, **send_kwargs)  # type: ignore[attr-defined]
        second_response.history.append(response)
        return second_response

    @vendor_retry()
    def _request_token(self) -> Response:
        # `capture=False` keeps the exchange out of HTTP sample capture: the response carries the
        # access token in a bare `access_token` field. The client secret travels in the body, so a
        # redirect must not replay it to another host.
        session = make_tracked_session(
            redact_values=(self._client_secret, self._refresh_token),
            capture=False,
            allow_redirects=False,
        )
        response = session.post(
            self._token_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
            timeout=TOKEN_TIMEOUT_SECONDS,
        )
        # The retries live here, not in the adapter: the 401 hook runs while the REST client has
        # the adapter retries turned off.
        raise_for_retryable_status(response, vendor="Zoho Desk", url=self._token_url)
        return response

    def _mint(self) -> _AccessToken:
        response = self._request_token()
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            body = {}

        access_token = body.get("access_token")
        if isinstance(access_token, str) and access_token:
            return _AccessToken(
                value=access_token, deadline=time.monotonic() + _token_lifetime_seconds(body.get("expires_in"))
            )

        error = body.get("error")
        if isinstance(error, str) and error in TOKEN_ERROR_MESSAGES:
            raise ZohoDeskAuthError(error)
        if isinstance(error, str):
            raise ZohoDeskTokenUnavailableError(
                f"Zoho Desk returned no access token (HTTP {response.status_code}): {error}"
            )
        response.raise_for_status()
        raise ZohoDeskTokenUnavailableError("Zoho Desk returned no access token and no error code")


def _auth(config: ZohoDeskSourceConfig, hosts: RegionHosts) -> ZohoDeskAuth:
    return ZohoDeskAuth(
        accounts_host=hosts.accounts_host,
        client_id=config.client_id,
        client_secret=config.client_secret,
        refresh_token=config.refresh_token,
    )


def _headers(organization_id: Optional[str]) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if organization_id:
        headers["orgId"] = organization_id
    return headers


def _list_params(endpoint: ZohoDeskEndpointConfig) -> dict[str, Any]:
    params: dict[str, Any] = dict(endpoint.extra_params or {})
    if endpoint.sort_by is not None:
        params["sortBy"] = endpoint.sort_by
    return params


def _record_id(row: Any) -> Optional[str]:
    record_id = row.get("id") if isinstance(row, dict) else None
    return None if record_id is None else str(record_id)


class ZohoDeskPaginator(OffsetPaginator):
    """Offset paging that drops a record which a page repeats from the page before it.

    For an endpoint with `drop_repeated_ids`, the first record of a page can be the last record of
    the page before it. The REST client pages with a copy of this object, so the paginator removes
    the record from the page itself. The last record ID travels in the resume state, so a resumed
    run still knows the last record of the page that the earlier attempt read.
    """

    def __init__(self, endpoint: ZohoDeskEndpointConfig) -> None:
        super().__init__(
            limit=endpoint.page_size,
            offset=endpoint.first_index,
            offset_param="from",
            limit_param="limit",
            total_path=None,
        )
        self._drop_repeated_ids = endpoint.drop_repeated_ids
        self.last_id: Optional[str] = None

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        # The parent decides whether a next page exists from the full page, before a record goes.
        super().update_state(response, data)
        if not self._drop_repeated_ids or not data:
            return
        previous_last_id = self.last_id
        self.last_id = _record_id(data[-1])
        if previous_last_id is not None and _record_id(data[0]) == previous_last_id:
            del data[0]

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        state = super().get_resume_state()
        if state is not None and self._drop_repeated_ids:
            state["last_id"] = self.last_id
        return state

    def set_resume_state(self, state: dict[str, Any]) -> None:
        super().set_resume_state(state)
        last_id = state.get("last_id")
        self.last_id = None if last_id is None else str(last_id)


def zoho_desk_source(
    config: ZohoDeskSourceConfig,
    endpoint_name: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ZohoDeskResumeConfig],
) -> SourceResponse:
    endpoint = ZOHO_DESK_ENDPOINTS.get(endpoint_name)
    if endpoint is None:
        raise ValueError(f"Unknown Zoho Desk schema: {endpoint_name}")
    hosts = resolve_hosts(config.region)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": f"{hosts.desk_host}{API_PATH}",
            "headers": _headers(config.organization_id),
            "auth": _auth(config, hosts),
            # A redirect must not carry the request, or the 401 hook, to another host.
            "allow_redirects": False,
        },
        "resource_defaults": {"write_disposition": "replace"},
        "resources": [
            {
                "name": endpoint.name,
                "table_format": "delta",
                "endpoint": {
                    "path": endpoint.path,
                    "params": _list_params(endpoint),
                    "data_selector": endpoint.data_selector,
                    "paginator": ZohoDeskPaginator(endpoint),
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.next_index, "last_id": resume.last_id}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(
                ZohoDeskResumeConfig(next_index=int(state["offset"]), last_id=state.get("last_id"))
            )

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint.name,
        items=lambda: resource,
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint.partition_key else None,
        partition_format="month" if endpoint.partition_key else None,
        partition_keys=[endpoint.partition_key] if endpoint.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(config: ZohoDeskSourceConfig) -> tuple[bool, Optional[str]]:
    """Mint one access token. Zoho ties a token's scopes to the refresh token, so this confirms the
    client and the refresh token, and each table's scope is checked when that table syncs."""
    try:
        hosts = resolve_hosts(config.region)
    except ValueError:
        return False, "Pick the data center your Zoho account uses."
    try:
        _auth(config, hosts).access_token()
    except ZohoDeskAuthError as error:
        return False, error.user_message
    except Exception:  # noqa: BLE001 — a credential probe must never raise out of source setup
        return False, "Could not get an access token from Zoho. Wait a minute, then try again."
    return True, None
