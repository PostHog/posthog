import json
import dataclasses
from datetime import date, datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.linode.settings import LINODE_ENDPOINTS

LINODE_BASE_URL = "https://api.linode.com/v4"

# Max allowed page_size is 500 (min 25). Using the max minimizes request count against the 200 req/min
# paginated-GET rate limit.
PAGE_SIZE = 500


@dataclasses.dataclass
class LinodeResumeConfig:
    # Next page (1-indexed) to fetch. The X-Filter header (built from the run's fixed watermark) and
    # page_size are constant across a run, so the page number alone is enough to resume.
    next_page: int


def _accept_headers() -> dict[str, str]:
    # The Bearer token is supplied via the framework auth config so its value is redacted from logs
    # and raised errors; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


def _format_filter_value(value: Any) -> Any:
    """Format an incremental cursor value for a Linode X-Filter comparison.

    Integer cursors (event id) pass through unchanged. Datetime/date cursors are rendered as the
    `YYYY-MM-DDTHH:MM:SS` form Linode uses for its own timestamp fields (no timezone offset)."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    return value


def _build_x_filter(field: str, value: Any) -> dict[str, Any]:
    """Build the JSON X-Filter body. Always orders ascending on the cursor field so pages arrive in
    the order SourceResponse.sort_mode ("asc") promises; adds a `+gte` bound when a watermark exists.

    The watermark is fixed for the whole run, so the header is built once and sent identically on
    every page request — the server applies the filter and order to the full result set, and
    pagination naturally terminates at the watermark (no client-side stop needed)."""
    x_filter: dict[str, Any] = {"+order_by": field, "+order": "asc"}
    if value is not None:
        x_filter[field] = {"+gte": _format_filter_value(value)}
    return x_filter


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    """Confirm the token is genuine by hitting /profile, which any valid token can read regardless of
    its granted scopes — so a token that only has scopes for some endpoints still validates."""
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{LINODE_BASE_URL}/profile",
        headers={"Authorization": f"Bearer {api_token}", **_accept_headers()},
    )
    if ok:
        return True, None
    if status == 401:
        return False, "Invalid Linode API token"
    if status is None:
        return False, "Could not reach the Linode API"
    # Don't surface the raw response body: Linode error bodies can echo account/resource details, and
    # this message is persisted on the source. The status code alone is enough to diagnose.
    return False, f"Linode API returned {status}"


def linode_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[LinodeResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = LINODE_ENDPOINTS[endpoint]

    headers = _accept_headers()
    # Attach the X-Filter header for incremental/append endpoints. Honor the user's chosen cursor
    # field, falling back to the endpoint's declared filterable field. On the first sync the watermark
    # is None, so we send only the ordering (no +gte bound) and pull the full available window.
    if config.incremental_field is not None and should_use_incremental_field:
        cursor_field = incremental_field or config.incremental_field
        headers["X-Filter"] = json.dumps(_build_x_filter(cursor_field, db_incremental_field_last_value))

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": LINODE_BASE_URL,
            "headers": headers,
            "auth": {"type": "bearer", "token": api_token},
            # Linode returns {data, page, pages, results}; `pages` is the total page count, so the
            # paginator stops after the last page rather than paying an extra empty-page request.
            "paginator": PageNumberPaginator(base_page=1, page_param="page", total_path="pages"),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"page_size": PAGE_SIZE},
                    "data_selector": "data",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the paginator state already points at the next
        # unfetched page and is saved AFTER the current page is yielded (and committed downstream), so
        # a crash resumes at the next page without re-fetching committed rows or skipping any.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(LinodeResumeConfig(next_page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # The X-Filter header orders results ascending on the cursor field, so rows arrive oldest-first
        # and the watermark advances safely after each batch.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
