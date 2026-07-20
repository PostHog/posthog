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
    BasePaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.guardian.settings import (
    GUARDIAN_ENDPOINTS,
    GuardianEndpointConfig,
)

GUARDIAN_BASE_URL = "https://content.guardianapis.com"

# The free developer tier caps page-size at 200; larger values are rejected.
PAGE_SIZE = 200


@dataclasses.dataclass
class GuardianResumeConfig:
    # The next page number to fetch. The API is 1-indexed. With `order-by=oldest` the result set is
    # ordered ascending and stable within a run, so a page number is a safe resume cursor.
    page: int = 1


def _format_from_date(value: Any) -> str | None:
    """Map the incremental cursor to the API's day-granular `from-date` (YYYY-MM-DD).

    The Guardian only filters by calendar date, not by time, so an incremental sync re-fetches the
    watermark day. Those re-pulled rows dedupe on the `id` primary key at merge time.
    """
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value:
        # Cursor persisted as an ISO string (e.g. "2026-07-02T13:12:10Z"); keep the date part.
        return value[:10]
    return None


def _build_paginator(config: GuardianEndpointConfig) -> BasePaginator:
    if config.paginated:
        # `search` / `tags` report `pages` (total number of pages) and paginate 1-indexed; stop
        # after the last page rather than paying one extra empty-page request.
        return PageNumberPaginator(base_page=1, page_param="page", total_path="response.pages")
    # `sections` / `editions` return everything in one response with no pagination metadata.
    return SinglePagePaginator()


def guardian_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[GuardianResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = GUARDIAN_ENDPOINTS[endpoint]

    # The api-key rides in the query string via framework auth, so its value is scrubbed from every
    # raised error message (and logged URL) automatically — no hand-rolled URL redaction needed.
    params: dict[str, Any] = {"page-size": PAGE_SIZE, "format": "json", **config.extra_params}

    endpoint_config: dict[str, Any] = {
        "path": config.path,
        "params": params,
        "data_selector": "response.results",
        # A 200 body without the `response` envelope means the shape changed — fail loud instead of
        # silently syncing 0 rows. A present-but-empty `results` list is still a valid 0-row page.
        "data_selector_required": True,
        "paginator": _build_paginator(config),
    }
    if config.supports_incremental:
        # Only /search honors a server-side forward cursor: `from-date` (day granular). `order-by=oldest`
        # + `order-date=published` (set via extra_params) keeps the watermark advancing.
        endpoint_config["incremental"] = {"start_param": "from-date", "convert": _format_from_date}

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": GUARDIAN_BASE_URL,
            "headers": {"Accept": "application/json"},
            "auth": {"type": "api_key", "api_key": api_key, "name": "api-key", "location": "query"},
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": endpoint_config,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-fetches
        # (and merge-dedupes) the last page rather than skipping it. We persist the next page to fetch.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(GuardianResumeConfig(page=int(state["page"])))

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
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Only `content` guarantees an order: `order-by=oldest` returns ascending `webPublicationDate`,
        # matching the watermark direction. The full-refresh reference endpoints have no `order-by`, so
        # their row order is unspecified — leave `sort_mode` unset rather than claim ascending.
        sort_mode="asc" if config.supports_incremental else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> bool:
    # /sections is a cheap, single-response endpoint — a genuine key returns 200, a bad one 401/403.
    # The api-key rides in the query string, so redact it from logged URLs and captured samples.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{GUARDIAN_BASE_URL}/sections?api-key={api_key}&page-size=1",
        headers={"Accept": "application/json"},
    )
    return ok
