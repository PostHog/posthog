from datetime import UTC, date, datetime
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.kalshi.settings import (
    KALSHI_ENDPOINTS,
    KalshiEndpointConfig,
)

KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"


@frozen
class KalshiResumeConfig:
    # Opaque pagination cursor from the previous response's `cursor` field.
    cursor: str


def _to_epoch_seconds(value: Any) -> Optional[int]:
    """Kalshi's `min_ts` filter wants the cutoff as integer seconds since epoch."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return int(value.timestamp())
    if isinstance(value, date):
        return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp())
    if isinstance(value, int | float):
        return int(value)
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except (ValueError, TypeError):
        return None


def _build_endpoint(config: KalshiEndpointConfig, should_use_incremental_field: bool) -> Endpoint:
    endpoint: Endpoint = {
        "path": config.path,
        "data_selector": config.data_key,
        # A missing wrapper key means the response shape changed; fail loud rather than syncing 0 rows.
        "data_selector_required": True,
    }

    if config.paginated:
        endpoint["params"] = {"limit": config.page_size}
        # Kalshi pages with an opaque `cursor` echoed at the response root, and omits it on the
        # last page. The paginator implements resume state, so a heartbeat timeout picks up mid-walk.
        endpoint["paginator"] = JSONResponseCursorPaginator(cursor_path="cursor", cursor_param="cursor")
    else:
        endpoint["paginator"] = SinglePagePaginator()

    if config.supports_incremental and should_use_incremental_field:
        endpoint["incremental"] = {
            "start_param": "min_ts",
            "cursor_path": "created_time",
            "convert": _to_epoch_seconds,
        }

    return endpoint


def kalshi_source(
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[KalshiResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = KALSHI_ENDPOINTS[endpoint]

    # Kalshi's market-data endpoints are public and take no credential, so no `auth` is configured.
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": KALSHI_BASE_URL,
            "headers": {"Accept": "application/json"},
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": _build_endpoint(config, should_use_incremental_field),
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"cursor": resume.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save after a page is yielded so a crash re-yields the last page (merge dedupes on the
        # primary key) instead of skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(KalshiResumeConfig(cursor=str(state["cursor"])))

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
        # Trades arrive strictly newest-first and the API offers no ascending option, so the
        # watermark can only advance once the walk completes.
        sort_mode="desc" if config.newest_first else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="day" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials() -> bool:
    # Nothing to authenticate; confirm the public API is reachable and answering so a source is
    # never created against an endpoint that has moved.
    ok, _status = validate_via_probe(
        make_tracked_session,
        f"{KALSHI_BASE_URL}/exchange/status",
        headers={"Accept": "application/json"},
    )
    return ok
