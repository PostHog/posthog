import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.retently.settings import RETENTLY_ENDPOINTS

RETENTLY_BASE_URL = "https://app.retently.com/api/v2"
# Documented maximum page size; the largest page minimises round trips against the ~150 req/min
# rate limit.
PAGE_SIZE = 1000
FIRST_PAGE = 1


@dataclasses.dataclass
class RetentlyResumeConfig:
    # Next page to fetch (1-based). Pages are requested in ascending creation order, so rows
    # created mid-sync land on the trailing pages and already-fetched pages stay stable; a crashed
    # sync resumes from the page after the last one yielded and merge dedupes any overlap.
    page: int = FIRST_PAGE


def _non_secret_headers() -> dict[str, str]:
    # The API key rides in the X-Api-Key header via the framework `api_key` auth so its value is
    # redacted from logs and error messages; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


def _format_start_date(value: Any) -> str:
    """Format an incremental cursor value as the ISO-8601 `...Z` string Retently's `startDate` expects.

    The API also accepts UNIX timestamps, so non-datetime values pass through as strings.
    """
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


class RetentlyPaginator(BasePaginator):
    """Page-number pagination for Retently list endpoints.

    Prefers the `pages` metadata when the API returns it — the docs place it inside `data` on some
    endpoints (feedback, companies, outbox) and at the top level on others (customers), so both
    spots are checked. Falls back to "a full page keeps going, a short page ends the loop" when the
    metadata is missing. An empty page always ends the loop.
    """

    def __init__(self, page: int = FIRST_PAGE, page_size: int = PAGE_SIZE, page_param: str = "page") -> None:
        super().__init__()
        self.page = page
        self.page_size = page_size
        self.page_param = page_param

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.page_param] = self.page

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.page_param] = self.page

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        item_count = len(data) if data else 0
        if item_count == 0:
            self._has_next_page = False
            return
        if self._has_more(response, self.page, item_count):
            self.page += 1
            self._has_next_page = True
        else:
            self._has_next_page = False

    def _has_more(self, response: Response, page: int, item_count: int) -> bool:
        try:
            body = response.json()
        except Exception:
            body = {}
        data = body.get("data") if isinstance(body, dict) else None
        for meta in (data if isinstance(data, dict) else {}, body if isinstance(body, dict) else {}):
            pages = meta.get("pages")
            if isinstance(pages, int):
                return page < pages
        return item_count >= self.page_size

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.page already points at the next page to fetch (update_state incremented it).
        return {"page": self.page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page = state.get("page")
        if page is not None:
            self.page = int(page)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"RetentlyPaginator(page={self.page})"


def retently_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RetentlyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = RETENTLY_ENDPOINTS[endpoint]
    supports_incremental = bool(config.incremental_fields)

    params: dict[str, Any] = {}
    paginator: BasePaginator
    if config.paginated:
        params["limit"] = PAGE_SIZE
        if config.sort_param is not None:
            params["sort"] = config.sort_param
        paginator = RetentlyPaginator()
    else:
        # Campaigns, templates and reports are documented without pagination and return the full
        # collection in one response — no page/limit/sort params.
        paginator = SinglePagePaginator()

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": params,
        "data_selector": config.data_selector,
        # A 200 whose payload isn't the expected list shape (an HTML proxy error, a transient
        # error envelope) is retried, matching the old transport which raised a retryable error
        # from its extraction step so one malformed page reissues instead of failing the sync.
        "data_selector_malformed_retryable": True,
        "paginator": paginator,
    }

    # `startDate` filters feedback server-side by creation date. Only sent when the endpoint is
    # incremental, incremental sync is on, and we have a watermark — the first incremental run and
    # full refreshes send no filter (the watermark row is re-fetched and merge dedupes it).
    if supports_incremental and should_use_incremental_field and db_incremental_field_last_value is not None:
        endpoint_config["incremental"] = {
            "start_param": "startDate",
            "cursor_path": config.incremental_fields[0]["field"],
            "convert": _format_start_date,
        }

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": RETENTLY_BASE_URL,
            "headers": _non_secret_headers(),
            "auth": {"type": "api_key", "api_key": api_key, "name": "X-Api-Key", "location": "header"},
        },
        "resource_defaults": {},
        "resources": [{"name": endpoint, "endpoint": endpoint_config}],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist AFTER a page is yielded and only when a next page remains, so a crash re-fetches
        # from the next page (already-yielded pages are persisted) and merge dedupes any overlap.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(RetentlyResumeConfig(page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if supports_incremental and should_use_incremental_field else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # The incremental endpoint requests ascending creation order via `sort=createdDate`, but we
        # could not verify against a live account that the param is honored, so "desc" keeps the
        # pipeline from checkpointing the watermark mid-sync — it's only persisted once a sync
        # completes successfully.
        sort_mode="desc" if supports_incremental else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Probe /ping to validate the API key.

    ``200`` reachable, ``401``/``403`` auth failure, any other HTTP status is inconclusive, and a
    transport failure (``status`` None) means the probe never reached Retently.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{RETENTLY_BASE_URL}/ping",
        headers={"X-Api-Key": api_key, "Accept": "application/json"},
        timeout=15,
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Retently API key"
    if status is not None:
        return False, f"Retently returned HTTP {status}"
    return False, "Could not connect to Retently"
