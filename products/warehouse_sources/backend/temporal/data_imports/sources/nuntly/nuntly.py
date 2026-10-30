from collections.abc import Iterable
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.nuntly.settings import ENDPOINTS, MAX_PAGE_SIZE

NUNTLY_BASE_URL = "https://api.nuntly.com"


@frozen
class NuntlyResumeConfig:
    cursor: Optional[str] = None
    # Fan-out tables checkpoint the shape `build_dependent_resource` emits: which parents finished
    # and where the current one stopped.
    fanout_state: Optional[dict[str, Any]] = None


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": NUNTLY_BASE_URL,
        "auth": {"type": "bearer", "token": api_key},
        # Every list endpoint returns `{"data": [...], "nextCursor": "<string|null>"}`.
        "paginator": JSONResponseCursorPaginator(cursor_path="nextCursor", cursor_param="cursor"),
    }


def nuntly_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[NuntlyResumeConfig],
) -> SourceResponse:
    endpoint_config = ENDPOINTS[endpoint]
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    resource: Iterable[Any]
    column_hints = None
    if endpoint_config.fanout is not None:

        def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state:
                resumable_source_manager.save_state(NuntlyResumeConfig(fanout_state=state))

        child_endpoint_extra: Endpoint = {"data_selector": "data"}
        if not endpoint_config.paginated:
            child_endpoint_extra["paginator"] = "single_page"

        resource = build_dependent_resource(
            endpoint_configs=ENDPOINTS,
            child_endpoint=endpoint,
            fanout=endpoint_config.fanout,
            client_config=_client_config(api_key),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            # Page sizes ride in the fan-out params: the unpaginated child takes no `limit`.
            page_size_param=None,
            parent_endpoint_extra={"data_selector": "data"},
            child_endpoint_extra=child_endpoint_extra,
            resume_hook=save_fanout_checkpoint if endpoint_config.checkpoint_fanout else None,
            initial_paginator_state=resume.fanout_state if resume and endpoint_config.checkpoint_fanout else None,
        )
    else:
        rest_config: RESTAPIConfig = {
            "client": _client_config(api_key),
            "resource_defaults": {"write_disposition": "replace"},
            "resources": [
                {
                    "name": endpoint,
                    "table_name": endpoint_config.table_name,
                    "endpoint": {
                        "path": endpoint_config.path,
                        "params": {"limit": MAX_PAGE_SIZE},
                        "data_selector": "data",
                    },
                    "table_format": "delta",
                }
            ],
        }

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            # Only persist when there's a next page to resume to; the Redis TTL cleans up on
            # completion. Save AFTER a page is yielded so a crash re-yields the last page (merge
            # dedupes on primary key) rather than skipping it.
            if state and state.get("cursor"):
                resumable_source_manager.save_state(NuntlyResumeConfig(cursor=str(state["cursor"])))

        top_level_resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state={"cursor": resume.cursor} if resume and resume.cursor else None,
        )
        resource = top_level_resource
        column_hints = top_level_resource.column_hints

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[endpoint_config.partition_key],
        column_hints=column_hints,
        supports_resume=endpoint_config.fanout is None or endpoint_config.checkpoint_fanout,
    )


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{NUNTLY_BASE_URL}/emails",
        headers={"Authorization": f"Bearer {api_key}"},
    )
