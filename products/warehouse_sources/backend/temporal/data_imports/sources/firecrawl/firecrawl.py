import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.firecrawl.settings import (
    FIRECRAWL_BASE_URL,
    FIRECRAWL_ENDPOINTS,
)

# Both the cursor endpoint (activity) and the offset endpoints (monitors, monitor checks) cap page
# size at 100. Ask for the maximum to minimize round trips.
PAGE_SIZE = 100


@dataclasses.dataclass
class FirecrawlResumeConfig:
    # team_activity cursor-pagination bookmark: the cursor for the next page to fetch.
    cursor: str | None = None
    # Offset for the offset-paginated endpoints (monitors, monitor_checks).
    offset: int | None = None
    # Legacy monitor_checks fan-out bookmark. Retained (with a default) so state saved by the old
    # transport still deserializes; the framework fan-out now checkpoints into `fanout_state`.
    monitor_id: str | None = None
    # monitor_checks fan-out resume state, as emitted by the shared dependent-resource paginator:
    # {"completed": [child_path, ...], "current": child_path | None, "child_state": {...} | None}.
    fanout_state: dict | None = None


def _auth_headers(api_key: str) -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so its value is redacted from logs;
    # this header form is used only for the credential probe, which bypasses the framework auth.
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": FIRECRAWL_BASE_URL,
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_key},
    }


def validate_credentials(api_key: str) -> bool:
    # credit-usage is a cheap, always-present team endpoint: a genuine key returns 200, an invalid or
    # revoked one 401. We only confirm the token itself here (see FirecrawlSource.validate_credentials).
    # Redact the bearer token from tracked logs/samples in case Firecrawl reflects it back.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{FIRECRAWL_BASE_URL}/v2/team/credit-usage",
        headers=_auth_headers(api_key),
    )
    return ok


def firecrawl_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FirecrawlResumeConfig],
) -> SourceResponse:
    cfg = FIRECRAWL_ENDPOINTS[endpoint]

    if cfg.fan_out_over_monitors:
        resource = _fan_out_resource(api_key, endpoint, team_id, job_id, resumable_source_manager)
    else:
        resource = _paginated_resource(api_key, endpoint, team_id, job_id, resumable_source_manager)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=cfg.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if cfg.partition_key else None,
        partition_format=cfg.partition_format if cfg.partition_key else None,
        partition_keys=[cfg.partition_key] if cfg.partition_key else None,
    )


def _paginated_resource(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[FirecrawlResumeConfig],
) -> Resource:
    cfg = FIRECRAWL_ENDPOINTS[endpoint]

    params: dict[str, Any] = {}
    if cfg.pagination == "cursor":
        paginator: Any = JSONResponseCursorPaginator(cursor_path="cursor", cursor_param="cursor")
        params["limit"] = PAGE_SIZE
    elif cfg.pagination == "offset":
        # No top-level total; termination is a short/empty page (OffsetPaginator default).
        paginator = OffsetPaginator(limit=PAGE_SIZE, total_path=None)
    else:
        paginator = SinglePagePaginator()

    endpoint_config: Endpoint = {
        "path": cfg.path,
        "params": params,
        "paginator": paginator,
        "data_selector": cfg.data_selector,
        # Index (not .get) semantics: a 200 body missing the selector means the response shape changed
        # - fail the sync loudly instead of silently replacing warehouse data with zero rows.
        "data_selector_required": True,
    }
    config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [
            {
                "name": endpoint,
                "table_name": endpoint,
                "write_disposition": "replace",
                "endpoint": endpoint_config,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if manager.can_resume():
        resume = manager.load_state()
        if resume is not None:
            if cfg.pagination == "cursor" and resume.cursor is not None:
                initial_paginator_state = {"cursor": resume.cursor}
            elif cfg.pagination == "offset" and resume.offset is not None:
                initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER the page is yielded so a crash re-yields
        # the last page (the primary key dedupes) rather than skipping it.
        if not state:
            return
        if cfg.pagination == "cursor" and state.get("cursor") is not None:
            manager.save_state(FirecrawlResumeConfig(cursor=state["cursor"]))
        elif cfg.pagination == "offset" and state.get("offset") is not None:
            manager.save_state(FirecrawlResumeConfig(offset=int(state["offset"])))

    return rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _fan_out_resource(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[FirecrawlResumeConfig],
) -> Resource:
    """Fan out over every monitor, paging each monitor's checks. The monitor list is fetched purely
    to drive the fan-out (the monitors table is synced by its own endpoint); each check row already
    carries its `monitorId`, so no parent field is injected. Single-hop fan-out is resumable: the
    shared paginator checkpoints per-monitor progress so a restart skips monitors already fully synced.
    """
    cfg = FIRECRAWL_ENDPOINTS[endpoint]
    monitors_cfg = FIRECRAWL_ENDPOINTS["monitors"]

    parent_resource: EndpointResource = {
        "name": "monitors",
        "table_name": "monitors",
        "write_disposition": "replace",
        "endpoint": {
            "path": monitors_cfg.path,
            "paginator": OffsetPaginator(limit=PAGE_SIZE, total_path=None),
            "data_selector": monitors_cfg.data_selector,
            "data_selector_required": True,
        },
    }
    child_resource: EndpointResource = {
        "name": endpoint,
        "table_name": endpoint,
        "write_disposition": "replace",
        "include_from_parent": [],
        "endpoint": {
            "path": cfg.path,
            "params": {"monitor_id": {"type": "resolve", "resource": "monitors", "field": "id"}},
            "paginator": OffsetPaginator(limit=PAGE_SIZE, total_path=None),
            "data_selector": cfg.data_selector,
            "data_selector_required": True,
        },
    }
    config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [parent_resource, child_resource],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if manager.can_resume():
        resume = manager.load_state()
        if resume is not None and resume.fanout_state is not None:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            manager.save_state(FirecrawlResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return next(r for r in resources if getattr(r, "name", None) == endpoint)
