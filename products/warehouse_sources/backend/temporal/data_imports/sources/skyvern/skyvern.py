import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.skyvern.settings import (
    SKYVERN_ENDPOINTS,
    SkyvernEndpointConfig,
)

SKYVERN_DEFAULT_BASE_URL = "https://api.skyvern.com"

# Every paginated list endpoint accepts page/page_size. 100 is the documented max for /v1/runs and a
# safe ceiling for the others (their only documented bound is a minimum of 1).
PAGE_SIZE = 100

# Bound per-workflow paging on incremental syncs so a huge run history can't scan unbounded. 100 pages
# * 100 rows = 10k runs per workflow within the created_at_start window. Full refreshes ignore this cap
# so a workflow's older runs are never permanently truncated.
MAX_PAGES_PER_WORKFLOW = 100


@dataclasses.dataclass
class SkyvernResumeConfig:
    # Next page number to fetch (1-based) for the simple (non-fan-out) endpoints.
    page: int = 1
    # Legacy bookmark from the hand-rolled fan-out implementation. Retained (with a default) only so
    # state persisted before the rest_source migration still deserializes; the framework fan-out is
    # checkpointed via `fanout_state` instead.
    workflow_permanent_id: Optional[str] = None
    # Framework dependent-resource resume snapshot for the runs fan-out:
    # {"completed": [child_path, ...], "current": child_path | None, "child_state": {...} | None}.
    fanout_state: Optional[dict[str, Any]] = None


def _base_url(base_url: str | None) -> str:
    return (base_url or SKYVERN_DEFAULT_BASE_URL).rstrip("/")


def _get_headers(api_key: str) -> dict[str, str]:
    return {"x-api-key": api_key, "Accept": "application/json"}


def _format_datetime_z(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC, which Skyvern's created_at_start filter expects."""
    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _to_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _created_at_start(
    config: SkyvernEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> str | None:
    """Build the created_at_start filter value from the incremental watermark.

    Subtracts the endpoint's lookback and clamps to now (a future-dated cursor would filter out every
    row). The re-pulled window is deduped by merge on the primary key.
    """
    if not (should_use_incremental_field and config.supports_incremental and db_incremental_field_last_value):
        return None
    dt = _to_datetime(db_incremental_field_last_value)
    if dt is None:
        return None
    if config.incremental_lookback:
        dt = dt - config.incremental_lookback
    now = datetime.now(UTC)
    aware = dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    if aware > now:
        dt = now
    return _format_datetime_z(dt)


def _client_config(api_key: str, base_url: str | None) -> ClientConfig:
    return {
        "base_url": _base_url(base_url),
        # Only the non-secret Accept header lives here; the API key rides the framework auth so it's
        # redacted from logs and raised error messages.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "api_key", "api_key": api_key, "name": "x-api-key", "location": "header"},
        # base_url is user-supplied — pin redirects off as an SSRF boundary so a hostile host can't
        # redirect the credentialed request to an internal address. The egress proxy is the load-bearing
        # control; this is defense-in-depth.
        "allow_redirects": False,
    }


def _simple_resource(
    config: SkyvernEndpointConfig,
    endpoint: str,
    client_config: ClientConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SkyvernResumeConfig],
) -> Resource:
    params: dict[str, Any] = {"page_size": PAGE_SIZE, **config.extra_params}

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # A Skyvern list is either a bare array (data_key None) or an object wrapping the
                    # rows under data_key (e.g. /v1/schedules -> {"schedules": [...]}). Mirror the old
                    # tolerant behavior: an unexpected shape yields 0 rows rather than failing loud.
                    "data_selector": config.data_key,
                    # 1-based paging; stop on the first empty page.
                    "paginator": PageNumberPaginator(base_page=1, page=1, page_param="page"),
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.page and resume.page > 1:
            initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(SkyvernResumeConfig(page=int(state["page"])))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _fan_out_resource(
    config: SkyvernEndpointConfig,
    endpoint: str,
    client_config: ClientConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SkyvernResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Resource:
    """Fan out over every workflow, pulling its runs from /v1/agents/{workflow_permanent_id}/runs.

    Incremental syncs bound each workflow's run list with created_at_start (watermark minus lookback).
    workflow_run_id is globally unique, so it is a sufficient primary key on its own.
    """
    created_at_start = _created_at_start(config, should_use_incremental_field, db_incremental_field_last_value)

    child_params: dict[str, Any] = {
        "workflow_permanent_id": {"type": "resolve", "resource": "workflows", "field": "workflow_permanent_id"},
        "page_size": PAGE_SIZE,
    }
    if created_at_start is not None:
        child_params["created_at_start"] = created_at_start

    # A full refresh (no created_at_start window) pages through every run so a workflow with more than
    # MAX_PAGES_PER_WORKFLOW * PAGE_SIZE runs is never permanently truncated. The cap only guards
    # runaway on incremental syncs, whose created_at_start window already bounds the volume.
    maximum_page = MAX_PAGES_PER_WORKFLOW if created_at_start is not None else None

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [
            {
                "name": "workflows",
                "write_disposition": "replace",
                "endpoint": {
                    "path": "/v1/agents",
                    "params": {"page_size": PAGE_SIZE, "only_workflows": "true"},
                    "paginator": PageNumberPaginator(base_page=1, page=1, page_param="page"),
                },
            },
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": child_params,
                    "paginator": PageNumberPaginator(base_page=1, page=1, page_param="page", maximum_page=maximum_page),
                },
            },
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        resumable_source_manager.save_state(SkyvernResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return next(r for r in resources if r.name == endpoint)


def validate_credentials(api_key: str, base_url: str | None) -> tuple[bool, str | None]:
    """Probe the cheapest list endpoint to confirm the API key is genuine."""
    url = f"{_base_url(base_url)}/v1/agents?page=1&page_size=1"
    # base_url is user-supplied, so treat it as an SSRF boundary: pin redirects off so a
    # malicious/self-hosted host can't bounce the API key to an internal address.
    ok, status = validate_via_probe(
        lambda: make_tracked_session(allow_redirects=False, redact_values=(api_key,)),
        url,
        headers=_get_headers(api_key),
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Skyvern API key"
    if status is None:
        return False, "Could not reach the Skyvern API"
    return False, f"Skyvern API returned status {status}"


def skyvern_source(
    api_key: str,
    base_url: str | None,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SkyvernResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SKYVERN_ENDPOINTS[endpoint]
    client_config = _client_config(api_key, base_url)

    if config.fan_out_over_workflows:
        resource = _fan_out_resource(
            config,
            endpoint,
            client_config,
            team_id,
            job_id,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    else:
        resource = _simple_resource(config, endpoint, client_config, team_id, job_id, resumable_source_manager)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # Skyvern list endpoints return newest-first and expose no sort param, so rows arrive
        # descending by created_at. In desc mode the pipeline persists the incremental watermark only
        # at successful job end, which is what we want for the runs fan-out: a partial run's max
        # created_at says nothing about workflows it never reached.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
