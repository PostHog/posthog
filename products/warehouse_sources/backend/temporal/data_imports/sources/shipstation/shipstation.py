import dataclasses
from datetime import date, datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from requests import Response
from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.settings import (
    SHIPSTATION_ENDPOINTS,
    ShipStationEndpointConfig,
)

SHIPSTATION_BASE_URL = "https://ssapi.shipstation.com"
# ShipStation list pages cap at 500 items.
PAGE_SIZE = 500

# All ShipStation v1 DateTime values are US Pacific time, not UTC.
SHIPSTATION_TZ = ZoneInfo("America/Los_Angeles")


@dataclasses.dataclass
class ShipStationResumeConfig:
    # ShipStation paginates with a 1-based page number; the framework's PageNumberPaginator resume
    # state is a single ``{"page": <next page>}`` dict, so it maps straight onto this existing field.
    page: int


class ShipStationPageNumberPaginator(PageNumberPaginator):
    """1-based page pagination over ShipStation's ``{<data_key>, page, pages}`` envelopes.

    Stops after the last page when the body carries a ``pages`` total, and falls back to short-page
    termination when it doesn't — matching the hand-rolled loop this replaces. Empty intermediate
    pages don't stop pagination (``stop_after_empty_page=False``); the ``pages`` total governs
    termination whenever it's present.
    """

    def __init__(self, page_size: int) -> None:
        super().__init__(base_page=1, page_param="page", total_path="pages", stop_after_empty_page=False)
        self._page_size = page_size

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if not self._has_next_page:
            return
        # Fall back to short-page termination only when the body lacks a ``pages`` total.
        try:
            body = response.json()
        except Exception:
            body = None
        has_pages_total = isinstance(body, dict) and body.get("pages") is not None
        if not has_pages_total and data is not None and len(data) < self._page_size:
            self._has_next_page = False


def _format_date_filter(value: Any) -> str:
    """Format an incremental cursor for ShipStation's date filters.

    The API both stores and filters in US Pacific time ('yyyy-mm-dd hh:mm:ss').
    Naive values are assumed to already be Pacific (they come from API rows);
    aware values are converted."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is None else value.astimezone(SHIPSTATION_TZ)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d 00:00:00")
    # Row values look like '2024-01-02T03:04:05.0000000'; the filter accepts the
    # space-separated form, so normalize the separator and drop fractions.
    text = str(value).replace("T", " ")
    return text.split(".")[0]


def _build_params(
    config: ShipStationEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    if config.paginated:
        params["pageSize"] = PAGE_SIZE

    if not config.incremental_params:
        return params

    cursor_field = incremental_field or config.incremental_fields[0]["field"]

    if should_use_incremental_field and db_incremental_field_last_value is not None:
        filter_param = config.incremental_params.get(cursor_field)
        if filter_param is not None:
            params[filter_param] = _format_date_filter(db_incremental_field_last_value)

    # Ascending sort on the cursor field (when the endpoint documents one) keeps
    # page boundaries stable and advances the incremental watermark monotonically.
    sort_by = config.sort_by.get(cursor_field)
    if sort_by is not None:
        params["sortBy"] = sort_by
        params["sortDir"] = "ASC"

    return params


def validate_credentials(api_key: str, api_secret: str) -> bool:
    """Confirm the key pair is valid with a cheap one-store listing probe."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key, api_secret)),
        f"{SHIPSTATION_BASE_URL}/stores",
        auth=HTTPBasicAuth(api_key, api_secret),
    )
    return ok


def shipstation_source(
    api_key: str,
    api_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ShipStationResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = SHIPSTATION_ENDPOINTS[endpoint]

    paginator = ShipStationPageNumberPaginator(PAGE_SIZE) if config.paginated else SinglePagePaginator()
    params = _build_params(config, should_use_incremental_field, db_incremental_field_last_value, incremental_field)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": SHIPSTATION_BASE_URL,
            "headers": {"Accept": "application/json"},
            # Basic auth via the framework so the secret is redacted from logs.
            "auth": {"type": "http_basic", "username": api_key, "password": api_secret},
            "paginator": paginator,
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # A missing/malformed data key is tolerated (treated as an empty page), matching
                    # the old _extract_items behaviour — so no data_selector_required. None selector
                    # means the whole body is the row list (bare-array endpoints).
                    "data_selector": config.data_key,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.paginated and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on primary key) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(ShipStationResumeConfig(page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
