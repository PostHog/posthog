import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    Endpoint,
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.housecall_pro.settings import (
    HOUSECALL_PRO_ENDPOINTS,
)

HOUSECALL_PRO_BASE_URL = "https://api.housecallpro.com"

# The vendor's own default is 10; raising it cuts round trips against an undisclosed rate limit.
# Pagination termination reads `total_pages` from the body, so a smaller honored page size still
# walks every page correctly.
PAGE_SIZE = 100

# Hard cap so a paginator that never sees `total_pages` drop below the current page can't loop forever.
MAX_PAGES = 100_000


@dataclasses.dataclass(frozen=False)  # resume state is rebuilt wholesale each save, not mutated in place
class HousecallProResumeConfig:
    # Next 1-indexed page to fetch.
    page: int


def _format_created_at_min(value: Any) -> str | None:
    """Format an incremental cursor as the ISO 8601 UTC timestamp `created_at_min` expects."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, str) and value:
        return value
    return None


def validate_credentials(api_key: str) -> bool:
    """Confirm the API key is genuine by fetching the account's company profile."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{HOUSECALL_PRO_BASE_URL}/company",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    return ok


def get_rows(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HousecallProResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = HOUSECALL_PRO_ENDPOINTS[endpoint]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    initial_paginator_state: Optional[dict[str, Any]] = {"page": resume.page} if resume is not None else None

    params: dict[str, Any] = {"page_size": PAGE_SIZE}
    if config.sort_field:
        # Ascending on the cursor field so the pipeline watermark advances safely and full-refresh
        # pages don't skip/duplicate rows inserted mid-sync.
        params["sort_by"] = config.sort_field
        params["sort_direction"] = "asc"

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": params,
        # A 200 body without the response key reads as an empty page and ends pagination.
        "data_selector": config.response_key,
        # `total_pages` in the body is the number of PAGES, so pagination stops after the last page
        # without paying an extra empty-page request.
        "paginator": PageNumberPaginator(
            base_page=1,
            page_param="page",
            total_path="total_pages",
            maximum_page=MAX_PAGES,
        ),
    }
    if config.supports_incremental and config.incremental_param and should_use_incremental_field:
        endpoint_config["incremental"] = {
            "start_param": config.incremental_param,
            "cursor_path": cast("str", config.sort_field),
            "convert": _format_created_at_min,
        }

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": HOUSECALL_PRO_BASE_URL,
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
        },
        "resources": [{"name": endpoint, "endpoint": endpoint_config}],
    }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the framework calls this AFTER a page is yielded
        # so a crash re-pulls from the next page rather than losing the page we just handed off —
        # the merge dedupes any overlap on the primary key.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(HousecallProResumeConfig(page=int(state["page"])))

    yield from rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def housecall_pro_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HousecallProResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = HOUSECALL_PRO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            team_id=team_id,
            job_id=job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
