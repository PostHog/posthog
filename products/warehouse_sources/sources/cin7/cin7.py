import time
import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from dateutil import parser
from requests import PreparedRequest, Request, Response

from products.warehouse_sources.sources.cin7.settings import CIN7_BASE_URL, CIN7_ENDPOINTS, PAGE_LIMIT, Cin7Endpoint
from products.warehouse_sources.sources.sdk import (
    AuthConfigBase,
    BasePaginator,
    Endpoint,
    EndpointResource,
    RESTAPIConfig,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    interruptible_wait,
    make_tracked_session,
    rest_api_resource,
)

# Cin7 Core allows 60 calls per minute for each API application, so one run sends at most one request a second.
MIN_REQUEST_INTERVAL_SECONDS = 1.0

# Cin7 Core documents no Retry-After header on a 429. With the default backoff ceiling of 60 s, eight
# attempts wait about two minutes in total, which is longer than the one-minute rate limit window.
MAX_RETRY_ATTEMPTS = 8

VALIDATION_TIMEOUT_SECONDS = 30


@dataclasses.dataclass(frozen=True)
class Cin7ResumeConfig:
    next_page: int


class Cin7Auth(AuthConfigBase):
    """Sends the account ID and application key in the two headers that Cin7 Core reads."""

    def __init__(self, account_id: str, application_key: str) -> None:
        self.account_id = account_id
        self.application_key = application_key

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        request.headers.update(_auth_headers(self.account_id, self.application_key))
        return request

    def secret_values(self) -> tuple[str, ...]:
        return tuple(value for value in (self.account_id, self.application_key) if value)


def _auth_headers(account_id: str, application_key: str) -> dict[str, str]:
    return {"api-auth-accountid": account_id, "api-auth-applicationkey": application_key}


class Cin7Paginator(BasePaginator):
    """Walks `Page` from 1 and stops on the last page.

    The last page is the first page that is empty or shorter than `Limit`, or the page that reaches
    the `Total` record count in the body. A page longer than `Limit` also stops the walk: an endpoint
    that ignores `Page` returns every row each time, and a second request would only repeat them.
    """

    def __init__(self, limit: int = PAGE_LIMIT) -> None:
        super().__init__()
        self.limit = limit
        self.page = 1
        self._last_request_at = 0.0

    def init_request(self, request: Request) -> None:
        self._set_page(request)
        self._last_request_at = time.monotonic()

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        row_count = len(data) if data else 0
        total = _total_records(response)
        if row_count != self.limit or (total is not None and self.page * self.limit >= total):
            self._has_next_page = False
            return
        self.page += 1
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < MIN_REQUEST_INTERVAL_SECONDS:
            interruptible_wait(MIN_REQUEST_INTERVAL_SECONDS - elapsed)
        self._set_page(request)
        self._last_request_at = time.monotonic()

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"page": self.page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page = state.get("page")
        if page is not None:
            self.page = int(page)
            self._has_next_page = True

    def _set_page(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["Page"] = self.page
        request.params["Limit"] = self.limit


def _total_records(response: Response) -> Optional[int]:
    try:
        body = response.json()
    except ValueError:
        return None
    total = body.get("Total") if isinstance(body, dict) else None
    return total if isinstance(total, int) else None


def format_cin7_datetime(value: Any) -> str:
    """Format a watermark as the UTC `yyyy-MM-ddTHH:mm:ss.fff` value that Cin7 Core filters expect."""
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, date):
        moment = datetime(value.year, value.month, value.day)
    else:
        moment = parser.isoparse(str(value))
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC).replace(tzinfo=None)
    return moment.isoformat(timespec="milliseconds")


def get_resource(
    endpoint: Cin7Endpoint,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> EndpointResource:
    is_incremental = should_use_incremental_field and endpoint.incremental_filter_param is not None
    params: dict[str, Any] = dict(endpoint.params)
    # The first incremental sync has no watermark and sends no filter, so it reads every row.
    if is_incremental and endpoint.incremental_filter_param and db_incremental_field_last_value is not None:
        params[endpoint.incremental_filter_param] = format_cin7_datetime(db_incremental_field_last_value)

    endpoint_config: Endpoint = {
        "path": endpoint.path,
        "data_selector": endpoint.data_selector,
        "params": params,
        "paginator": Cin7Paginator() if endpoint.paginated else SinglePagePaginator(),
    }

    return {
        "name": endpoint.name,
        "table_name": endpoint.name,
        "primary_key": endpoint.primary_keys,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if is_incremental else "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def cin7_source(
    account_id: str,
    application_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[Cin7ResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    endpoint_config = CIN7_ENDPOINTS[endpoint]

    config: RESTAPIConfig = {
        "client": {
            "base_url": CIN7_BASE_URL,
            "auth": Cin7Auth(account_id, application_key),
            "max_retries": MAX_RETRY_ATTEMPTS,
        },
        "resource_defaults": {},
        "resources": [get_resource(endpoint_config, should_use_incremental_field, db_incremental_field_last_value)],
    }

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    initial_paginator_state = {"page": resume_config.next_page} if resume_config is not None else None

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(Cin7ResumeConfig(next_page=int(state["page"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint_config.name,
        items=lambda: resource,
        primary_keys=endpoint_config.primary_keys,
    )


def validate_credentials(account_id: str, application_key: str) -> tuple[bool, str | None]:
    try:
        response = make_tracked_session(redact_values=(account_id, application_key)).get(
            f"{CIN7_BASE_URL}/me",
            headers=_auth_headers(account_id, application_key),
            timeout=VALIDATION_TIMEOUT_SECONDS,
        )
    except Exception:
        return False, "Could not connect to Cin7 Core. Try again in a few minutes."

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return (
            False,
            "Cin7 Core rejected the account ID or application key. Copy both values from Integrations > API in Cin7 Core.",
        )
    if response.status_code == 429:
        return False, "Cin7 Core rate limited the request. Wait a minute, then try again."
    return False, f"Cin7 Core returned an unexpected status ({response.status_code}). Try again in a few minutes."
