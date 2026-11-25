import time
from collections.abc import Callable
from typing import Any, Optional

from requests import PreparedRequest, Response

from products.warehouse_sources.sources.sdk import (
    DEFAULT_RETRY,
    AuthConfigBase,
    OffsetPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    frozen,
    make_tracked_session,
    rest_api_resource,
)
from products.warehouse_sources.sources.zoho_desk._config import ZohoDeskSourceConfig
from products.warehouse_sources.sources.zoho_desk.settings import ZOHO_DESK_ENDPOINTS, ZohoDeskEndpointConfig

API_PATH = "/api/v1"
TOKEN_PATH = "/oauth/v2/token"
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

# `DEFAULT_RETRY` retries only GET, HEAD, and OPTIONS. The token exchange is a POST, so a 5xx from
# the accounts host would otherwise fail the run on the first attempt. Repeating a refresh-token
# exchange is safe, because each exchange only mints a new access token.
TOKEN_RETRY = DEFAULT_RETRY.new(allowed_methods=frozenset(DEFAULT_RETRY.allowed_methods or ()) | {"POST"})


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

    Zoho limits how many access tokens one refresh token can mint in a short period, and each table
    sync mints its own. This error stays retryable so that a later attempt can mint one.
    """


@frozen
class ZohoDeskResumeConfig:
    next_index: int


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
    """Exchanges the refresh token for an access token and keeps it until shortly before it expires.

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
        self._token: Optional[str] = None
        self._deadline: float = 0.0

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        request.headers["Authorization"] = self._authorization()
        request.register_hook("response", self._resend_with_new_token)
        return request

    def secret_values(self) -> tuple[str, ...]:
        return tuple(value for value in (self._client_secret, self._refresh_token, self._token) if value)

    def access_token(self) -> str:
        if self._token is None or time.monotonic() >= self._deadline - TOKEN_REFRESH_MARGIN_SECONDS:
            self._token = self._mint()
        return self._token

    def _authorization(self) -> str:
        return f"Zoho-oauthtoken {self.access_token()}"

    def _resend_with_new_token(self, response: Response, **send_kwargs: Any) -> Response:
        """Send a request that got a 401 once more, with a newly minted token.

        Zoho keeps a limited number of access tokens alive for each refresh token, and each table
        sync mints its own. A token can therefore stop working before it expires, when other syncs
        of the same source mint theirs. The adapter sends the copy directly and does not run this
        hook again, so a second 401 goes back to the caller as a real credential failure.
        """
        if response.status_code != 401:
            return response
        # Read the body so that the connection goes back to the pool before the second request.
        _ = response.content
        self._token = None
        resent = response.request.copy()
        resent.headers["Authorization"] = self._authorization()
        second_response: Response = response.connection.send(resent, **send_kwargs)  # type: ignore[attr-defined]
        second_response.history.append(response)
        return second_response

    def _mint(self) -> str:
        # `capture=False` keeps the exchange out of HTTP sample capture: the response carries the
        # access token in a bare `access_token` field. The client secret travels in the body, so a
        # redirect must not replay it to another host.
        session = make_tracked_session(
            retry=TOKEN_RETRY,
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
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            body = {}

        access_token = body.get("access_token")
        if isinstance(access_token, str) and access_token:
            self._deadline = time.monotonic() + _token_lifetime_seconds(body.get("expires_in"))
            return access_token

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


def _first_occurrence_filter() -> Callable[[dict[str, Any]], bool]:
    seen: set[str] = set()

    def keep(row: dict[str, Any]) -> bool:
        record_id = row.get("id")
        if record_id is None:
            return True
        key = str(record_id)
        if key in seen:
            return False
        seen.add(key)
        return True

    return keep


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
                    "paginator": OffsetPaginator(
                        limit=endpoint.page_size,
                        offset=endpoint.first_index,
                        offset_param="from",
                        limit_param="limit",
                        total_path=None,
                    ),
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.next_index}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(ZohoDeskResumeConfig(next_index=int(state["offset"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    if endpoint.drop_repeated_ids:
        resource.add_filter(_first_occurrence_filter())

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
