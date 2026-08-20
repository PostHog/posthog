from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.polymarket.settings import (
    POLYMARKET_ENDPOINTS,
    PolymarketEndpointConfig,
)

POLYMARKET_BASE_URL = "https://gamma-api.polymarket.com"


@frozen
class PolymarketResumeConfig:
    # Keyset endpoints resume from an opaque cursor; offset endpoints resume from a row offset.
    # Exactly one is set, matching the endpoint's pagination style.
    cursor: Optional[str] = None
    offset: Optional[int] = None


def _build_endpoint(config: PolymarketEndpointConfig) -> Endpoint:
    # `order=id&ascending=true` is what makes paging stable. Without an explicit order the offset
    # endpoints return rows in an unspecified order, so a row inserted mid-sync shifts every later
    # page and silently skips or duplicates rows.
    params: dict[str, Any] = {"limit": config.page_size, "order": "id", "ascending": "true"}

    endpoint: Endpoint = {"path": config.path, "params": params}

    if config.pagination == "keyset":
        endpoint["data_selector"] = config.data_key
        # A missing wrapper key means the response shape changed; fail loud rather than syncing 0 rows.
        endpoint["data_selector_required"] = True
        # `next_cursor` is echoed at the response root and omitted on the last page; it is sent back
        # as `after_cursor`.
        endpoint["paginator"] = JSONResponseCursorPaginator(cursor_path="next_cursor", cursor_param="after_cursor")
    else:
        # These endpoints return a bare JSON array, so there is no key to select. Paging past the
        # end returns an empty array, which is what stops the walk.
        endpoint["paginator"] = OffsetPaginator(
            limit=config.page_size,
            total_path=None,
            stop_after_empty_page=True,
        )

    return endpoint


def polymarket_source(
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PolymarketResumeConfig],
) -> SourceResponse:
    config = POLYMARKET_ENDPOINTS[endpoint]

    # Gamma's read endpoints are public and take no credential, so no `auth` is configured.
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": POLYMARKET_BASE_URL,
            "headers": {"Accept": "application/json"},
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": _build_endpoint(config),
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            if config.pagination == "keyset" and resume.cursor is not None:
                initial_paginator_state = {"cursor": resume.cursor}
            elif config.pagination == "offset" and resume.offset is not None:
                initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save after a page is yielded so a crash re-yields the last page (merge dedupes on the
        # primary key) instead of skipping it.
        if not state:
            return
        if config.pagination == "keyset":
            if state.get("cursor"):
                resumable_source_manager.save_state(PolymarketResumeConfig(cursor=str(state["cursor"])))
        elif state.get("offset") is not None:
            resumable_source_manager.save_state(PolymarketResumeConfig(offset=int(state["offset"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        # Every table is full refresh, so no watermark is ever sent.
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # Rows come back ordered by ascending id, which is also roughly creation order.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials() -> bool:
    # Nothing to authenticate; confirm the public API is reachable so a source is never created
    # against an endpoint that has moved.
    ok, _status = validate_via_probe(
        make_tracked_session,
        f"{POLYMARKET_BASE_URL}/status",
        headers={"Accept": "application/json"},
    )
    return ok
