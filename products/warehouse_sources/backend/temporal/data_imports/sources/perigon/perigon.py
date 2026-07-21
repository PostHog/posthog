import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Response
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.perigon.settings import PERIGON_ENDPOINTS

# Current canonical host; api.goperigon.com is the legacy alias and serves the same API.
PERIGON_BASE_URL = "https://api.perigon.io"

PAGE_SIZE = 100
# Perigon caps the search result window at 10,000 rows (page * size), so with size=100 the
# last reachable page index is 99. Incremental syncs self-heal past the cap: the watermark
# advances with every batch, so the next run picks up where the capped one stopped.
MAX_PAGE = 99


@dataclasses.dataclass
class PerigonResumeConfig:
    # Next zero-based page to fetch, as reported by the framework paginator state.
    page: int


class PerigonPaginator(PageNumberPaginator):
    """Zero-based page/`size` pagination over Perigon's wrapped list responses.

    Perigon exposes no total-pages field, so a page shorter than the requested size is the
    last page; stopping on it avoids the extra empty-page request. The page cap mirrors the
    API's 10,000-row search window — a full page at the cap is logged since rows may remain.
    """

    def __init__(self, page_size: int, endpoint: str, logger: Optional[FilteringBoundLogger] = None) -> None:
        super().__init__(base_page=0, page_param="page", maximum_page=MAX_PAGE)
        self._page_size = page_size
        self._endpoint = endpoint
        self._logger = logger

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and data is not None and len(data) < self._page_size:
            self._has_next_page = False
            return
        if (
            not self._has_next_page
            and data is not None
            and len(data) >= self._page_size
            and self.page > (self.maximum_page or 0)
            and self._logger is not None
        ):
            self._logger.warning(
                "Perigon pagination depth cap reached; remaining rows are deferred to later syncs",
                endpoint=self._endpoint,
                page=self.page,
            )


def _format_datetime(value: Any) -> str:
    """Format a datetime/date cursor as `yyyy-MM-ddThh:mm:ssZ` (ISO 8601, UTC) for Perigon's
    date filters."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    else:
        # Already a string (e.g. an ISO timestamp persisted as the cursor) — pass through.
        return str(value)
    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _clamp_future_value_to_now(value: Any) -> Any:
    """Cap a future datetime cursor at now — a future-dated lower-bound filter would silently
    match nothing and stall the incremental sync."""
    now = datetime.now(UTC)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return now if aware > now else value
    if isinstance(value, date):
        return now.date() if value > now.date() else value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
        aware = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        return now if aware > now else value
    return value


def get_resource(
    endpoint: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    logger: Optional[FilteringBoundLogger] = None,
) -> EndpointResource:
    config = PERIGON_ENDPOINTS[endpoint]

    params: dict[str, Any] = {"size": PAGE_SIZE}
    # Incremental runs must walk the cursor field even before a watermark exists so the
    # pipeline's ordering assumption (sort_mode) holds from the first sync.
    sort_by = (
        config.incremental_sort_by
        if should_use_incremental_field and config.incremental_sort_by
        else config.full_refresh_sort_by
    )
    if sort_by:
        params["sortBy"] = sort_by

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": params,
        "data_selector": config.data_selector,
        "data_selector_required": True,
        "paginator": PerigonPaginator(PAGE_SIZE, endpoint, logger),
    }

    # Only filter server-side once a watermark exists; the first incremental sync reads from
    # the beginning of what the account can access.
    if should_use_incremental_field and config.incremental_param and db_incremental_field_last_value is not None:
        endpoint_config["incremental"] = {
            "start_param": config.incremental_param,
            "cursor_path": config.incremental_fields[0]["field"],
            "convert": lambda value: _format_datetime(_clamp_future_value_to_now(value)),
        }

    return {
        "name": endpoint,
        "table_name": endpoint,
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def perigon_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PerigonResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    logger: Optional[FilteringBoundLogger] = None,
) -> SourceResponse:
    config = PERIGON_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": PERIGON_BASE_URL,
            "auth": {"type": "bearer", "token": api_key},
            "headers": {"Accept": "application/json"},
        },
        "resource_defaults": {},
        "resources": [get_resource(endpoint, should_use_incremental_field, db_incremental_field_last_value, logger)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is yielded so a crash re-yields the last page (merge dedupes)
        # rather than skipping it. A None state means no page remains — nothing to persist.
        if state is not None and state.get("page") is not None:
            resumable_source_manager.save_state(PerigonResumeConfig(page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_key: str, path: Optional[str] = None) -> tuple[bool, int | None]:
    """Probe one cheap endpoint and report (is_valid, status_code).

    Defaults to the articles endpoint (Perigon's core dataset); pass a specific endpoint
    path to confirm the key's plan covers that dataset.
    """
    probe_path = path or PERIGON_ENDPOINTS["articles"].path
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{PERIGON_BASE_URL}{probe_path}?size=1",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
