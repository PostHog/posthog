import time
import logging
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import PreparedRequest, Request, Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.airwallex.settings import (
    AIRWALLEX_ENDPOINTS,
    AirwallexEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

logger = logging.getLogger(__name__)

AIRWALLEX_LIVE_BASE_URL = "https://api.airwallex.com"
AIRWALLEX_DEMO_BASE_URL = "https://api-demo.airwallex.com"

LOGIN_PATH = "/api/v1/authentication/login"
REQUEST_TIMEOUT_SECONDS = 30.0
# Access tokens last 30 minutes. Re-mint a little early so a long page fetch can't start with a
# token that expires mid-flight.
TOKEN_REFRESH_MARGIN_SECONDS = 120.0
# Fallback lifetime when the login response omits or malforms `expires_at`.
DEFAULT_TOKEN_LIFETIME_SECONDS = 25 * 60
# `page_num` is capped at 2000 by the API, so a page-number walk can reach at most
# 2000 * page_size rows. Stopping at the cap and logging beats looping on rejected pages.
MAX_PAGE_NUM = 2000


class AirwallexAuthError(Exception):
    pass


def base_url_for(environment: str) -> str:
    return AIRWALLEX_DEMO_BASE_URL if environment == "demo" else AIRWALLEX_LIVE_BASE_URL


@frozen
class AirwallexResumeConfig:
    # Page-number endpoints resume from the next page index; cursor endpoints from the opaque
    # `page_after` token. Exactly one is set, matching the endpoint's pagination style.
    page_num: Optional[int] = None
    cursor: Optional[str] = None


def _to_iso8601(value: Any) -> Optional[str]:
    """Airwallex's `from_*` filters want an ISO8601 instant, for example 2026-08-19T12:00:00Z."""
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=UTC)
    elif isinstance(value, date):
        moment = datetime(value.year, value.month, value.day, tzinfo=UTC)
    elif isinstance(value, int | float):
        moment = datetime.fromtimestamp(float(value), tz=UTC)
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
        moment = parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class AirwallexAuth(AuthConfigBase):
    """Mints and caches the 30-minute access token Airwallex issues from its login endpoint.

    The login call is not OAuth2: it is a bodyless POST carrying the client id and API key as
    `x-client-id` / `x-api-key` headers, answering 201 with `{"token", "expires_at"}`. The framework
    `oauth2` auth would send a `grant_type` body instead, so this mints the token itself and puts it
    on `Authorization` for every later request.
    """

    def __init__(self, client_id: str, api_key: str, base_url: str) -> None:
        self.client_id = client_id
        self.api_key = api_key
        self.base_url = base_url
        self._token: Optional[str] = None
        self._deadline: float = 0.0

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        request.headers["Authorization"] = f"Bearer {self._get_token()}"
        return request

    def secret_values(self) -> tuple[str, ...]:
        # The API key and the minted token are both secrets; redacting them here masks them in
        # logged URLs, headers, sampled bodies, and raised errors.
        return tuple(value for value in (self.api_key, self._token) if value)

    def _get_token(self) -> str:
        if self._token is None or time.monotonic() >= self._deadline - TOKEN_REFRESH_MARGIN_SECONDS:
            self._mint()
        assert self._token is not None
        return self._token

    def _mint(self) -> None:
        # `capture=False`: the login response carries the minted bearer under `token`, a generic
        # field name the name-based sample scrubber doesn't recognise, so capture would persist a
        # live credential.
        session = make_tracked_session(redact_values=(self.api_key,), capture=False)
        response = session.post(
            f"{self.base_url}{LOGIN_PATH}",
            headers={
                "x-client-id": self.client_id,
                "x-api-key": self.api_key,
                "Accept": "application/json",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
            # The token endpoint receives the API key, so never follow a redirect that would
            # replay those headers to another host.
            allow_redirects=False,
        )
        response.raise_for_status()
        payload = response.json()

        token = payload.get("token")
        if not token:
            raise AirwallexAuthError("Airwallex login succeeded but returned no token")

        self._token = str(token)
        self._deadline = time.monotonic() + _token_lifetime_seconds(payload.get("expires_at"))


def _token_lifetime_seconds(expires_at: Any) -> float:
    """Seconds until `expires_at`, falling back to a conservative default when it can't be read."""
    if not expires_at:
        return DEFAULT_TOKEN_LIFETIME_SECONDS
    raw = str(expires_at)
    # Airwallex stamps the offset without a colon (+0000), which fromisoformat rejects before 3.11
    # semantics and which no other source in the tree emits, so normalize it first.
    candidates = (raw.replace("Z", "+00:00"), raw)
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        remaining = (parsed - datetime.now(UTC)).total_seconds()
        # A clock skew or an already-expired stamp must not produce a negative lifetime, which
        # would re-mint on every single request.
        return remaining if remaining > 0 else DEFAULT_TOKEN_LIFETIME_SECONDS
    return DEFAULT_TOKEN_LIFETIME_SECONDS


class AirwallexPageNumberPaginator(BasePaginator):
    """Zero-based page numbers, stopping on the body's `has_more` flag.

    `has_more` is authoritative, so the walk stops without paying for an extra empty page. An empty
    page also stops it, in case the flag is missing. The API caps `page_num` at 2000; reaching that
    cap stops the walk and logs, rather than requesting pages the API will reject.
    """

    def __init__(self, page_num: int = 0, page_param: str = "page_num", endpoint: str = "") -> None:
        super().__init__()
        self.page_num = page_num
        self.page_param = page_param
        self.endpoint = endpoint

    def init_request(self, request: Request) -> None:
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return

        try:
            body = response.json()
        except Exception:
            body = {}

        has_more = body.get("has_more") if isinstance(body, dict) else None
        if has_more is False:
            self._has_next_page = False
            return

        self.page_num += 1

        if self.page_num > MAX_PAGE_NUM:
            logger.warning(
                "Airwallex page-number cap reached; endpoint may be truncated",
                extra={"endpoint": self.endpoint, "max_page_num": MAX_PAGE_NUM},
            )
            self._has_next_page = False
            return

        # `has_more` missing (None) with a full page: keep walking and let the empty-page check stop us.
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def _apply(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.page_param] = self.page_num

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"page_num": self.page_num} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page_num = state.get("page_num")
        if page_num is not None:
            self.page_num = int(page_num)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"AirwallexPageNumberPaginator(page_num={self.page_num})"


def _make_drop_map(drop_fields: tuple[str, ...]) -> Any:
    def _drop(item: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in item.items() if key not in drop_fields}

    return _drop


def _build_endpoint(config: AirwallexEndpointConfig, should_use_incremental_field: bool) -> Endpoint:
    endpoint: Endpoint = {
        "path": config.path,
        "params": {"page_size": config.page_size},
        "data_selector": "items",
        # A missing `items` key means the response shape changed; fail loud rather than syncing 0 rows.
        "data_selector_required": True,
        # An account with no rows for a resource answers with an empty envelope.
        "data_selector_empty_ok": True,
    }

    if config.pagination == "page_num":
        endpoint["paginator"] = AirwallexPageNumberPaginator(endpoint=config.name)
    else:
        # The cursor arrives as `page_after` and goes back out as `page`.
        endpoint["paginator"] = JSONResponseCursorPaginator(cursor_path="page_after", cursor_param="page")

    if should_use_incremental_field:
        endpoint["incremental"] = {
            "start_param": config.start_param,
            "cursor_path": config.cursor_field,
            "convert": _to_iso8601,
        }

    return endpoint


def airwallex_source(
    client_id: str,
    api_key: str,
    environment: str,
    api_version: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AirwallexResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = AIRWALLEX_ENDPOINTS[endpoint]
    base_url = base_url_for(environment)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url,
            "headers": {
                "Accept": "application/json",
                # Pinning the version keeps response shapes stable when Airwallex ships a new one.
                "x-api-version": api_version,
            },
            "auth": AirwallexAuth(client_id, api_key, base_url),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": _build_endpoint(config, should_use_incremental_field),
                # Strip live credentials (e.g. PaymentIntents/Customers `client_secret`) before a
                # row lands in the warehouse.
                **({"data_map": _make_drop_map(config.drop_fields)} if config.drop_fields else {}),
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            if config.pagination == "page_num" and resume.page_num is not None:
                initial_paginator_state = {"page_num": resume.page_num}
            elif config.pagination == "cursor" and resume.cursor is not None:
                initial_paginator_state = {"cursor": resume.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save after a page is yielded so a crash re-yields the last page (merge dedupes on the
        # primary key) instead of skipping it.
        if not state:
            return
        if config.pagination == "page_num":
            if state.get("page_num") is not None:
                resumable_source_manager.save_state(AirwallexResumeConfig(page_num=int(state["page_num"])))
        elif state.get("cursor"):
            resumable_source_manager.save_state(AirwallexResumeConfig(cursor=str(state["cursor"])))

    last_value = db_incremental_field_last_value if should_use_incremental_field else None

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # Airwallex documents an order for only one of its list endpoints, and that one is
        # descending. Declaring "desc" is the safe reading either way: the pipeline then writes the
        # watermark once the whole run finishes, instead of advancing it after every batch, so an
        # endpoint that turns out to return newest-first cannot strand older rows.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(client_id: str, api_key: str, environment: str) -> tuple[bool, Optional[str]]:
    """Confirm the client id and API key mint a token. Returns (is_valid, error_message)."""
    base_url = base_url_for(environment)
    try:
        AirwallexAuth(client_id, api_key, base_url)._get_token()
    except Exception:
        # A probe must never raise out of source creation.
        return False, "Airwallex rejected these credentials. Check the client ID and API key, then try again."
    return True, None
