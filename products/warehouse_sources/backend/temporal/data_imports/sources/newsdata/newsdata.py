import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    Endpoint,
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ApiKeyAuthConfig,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.newsdata.settings import (
    NEWSDATA_ENDPOINTS,
    NewsDataEndpointConfig,
)

NEWSDATA_BASE_URL = "https://newsdata.io/api/1"


@dataclasses.dataclass
class NewsDataResumeConfig:
    # Opaque `nextPage` cursor token to resume pagination from. None means "start at the first page".
    next_page: str | None = None


def _auth_config(api_key: str) -> ApiKeyAuthConfig:
    # NewsData accepts the key as an `apikey` query param or the `X-ACCESS-KEY` header. We use the
    # header (via framework auth) so the secret is redacted from logs and never lands in a request URL.
    return {
        "type": "api_key",
        "name": "X-ACCESS-KEY",
        "api_key": api_key,
        "location": "header",
    }


def _to_from_date(value: Any) -> str | None:
    """Reduce an incremental watermark to the `YYYY-MM-DD` string NewsData's `from_date` expects.

    The watermark comes back as a datetime (parsed by the pipeline), a date, or a raw string
    depending on how it was stored; NewsData's date filter is day-granular either way.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).date().isoformat() if value.tzinfo else value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    # Fall back to the leading YYYY-MM-DD of a string like "2024-01-15 12:34:56".
    return str(value)[:10]


def _initial_from_date(config: NewsDataEndpointConfig) -> Optional[date]:
    """First incremental sync floor: instead of crawling the entire (up to 7-year) archive, the very
    first sync only pulls the trailing N days. Later syncs advance from the stored watermark.
    """
    if config.default_lookback_days is None:
        return None
    return (datetime.now(UTC) - timedelta(days=config.default_lookback_days)).date()


def validate_credentials(api_key: str) -> bool:
    # The sources catalog is the cheapest authenticated probe: no pagination, small body, and it only
    # needs a valid key. An invalid or missing key returns HTTP 401.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{NEWSDATA_BASE_URL}/sources",
        headers={"X-ACCESS-KEY": api_key, "Accept": "application/json"},
    )
    return ok


def get_rows(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[NewsDataResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = NEWSDATA_ENDPOINTS[endpoint]

    # `nextPage` is an opaque cursor token surfaced in the body and echoed back as the `page` query
    # param. /sources rejects `page`, so it never paginates even if a stray cursor is present.
    paginator: JSONResponseCursorPaginator | SinglePagePaginator = (
        JSONResponseCursorPaginator(cursor_path="nextPage", cursor_param="page")
        if config.supports_pagination
        else SinglePagePaginator()
    )

    endpoint_config: Endpoint = {
        "path": config.path,
        # `size` is intentionally omitted — the page size is plan-capped and passing an over-cap value
        # 4xxs, so we let the API apply its own default.
        "params": {},
        # A missing `results` key reads as an empty page (matching the API's "no data" signal).
        "data_selector": "results",
        "paginator": paginator,
        # NewsData reports hard failures (unsupported param, quota exhausted) in a 200-body envelope
        # (`{"status": "error", ...}`); fail loud instead of syncing 0 rows. Scoped to HTTP 200 so
        # 401/403 still fall through to raise_for_status, which get_non_retryable_errors matches on.
        "response_actions": [
            {
                "status_code": 200,
                "content": '"status":"error"',
                "action": "raise",
                "message": "NewsData.io returned an error response. This is usually an unsupported parameter or an exhausted daily request quota — check your plan on the NewsData.io dashboard.",
            }
        ],
    }

    # Only date-filter endpoints (archive, crypto) accept from_date; on the first incremental sync
    # the lookback floor seeds it, on later syncs the stored watermark advances it.
    if config.supports_date_filter and should_use_incremental_field:
        incremental: IncrementalConfig = {
            "start_param": "from_date",
            "cursor_path": "pubDate",
            "initial_value": _to_from_date(_initial_from_date(config)),
            "convert": _to_from_date,
        }
        endpoint_config["incremental"] = incremental

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": NEWSDATA_BASE_URL,
            "headers": {"Accept": "application/json"},
            "auth": _auth_config(api_key),
        },
        "resources": [{"name": endpoint, "endpoint": endpoint_config}],
    }

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    initial_paginator_state: Optional[dict[str, Any]] = None
    if resume is not None and resume.next_page:
        initial_paginator_state = {"cursor": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the framework calls this AFTER a page is yielded so a
        # crash re-yields the next page rather than skipping it (the merge dedupes on the primary key).
        if state and state.get("cursor") is not None:
            resumable_source_manager.save_state(NewsDataResumeConfig(next_page=str(state["cursor"])))

    yield from rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def newsdata_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[NewsDataResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = NEWSDATA_ENDPOINTS[endpoint]

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
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
