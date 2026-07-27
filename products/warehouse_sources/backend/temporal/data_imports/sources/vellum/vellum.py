import dataclasses
from collections.abc import Iterable
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.vellum.settings import (
    VELLUM_BASE_URL,
    VELLUM_ENDPOINTS,
    VellumEndpointConfig,
)

PAGE_SIZE = 100

# The workflow deployment that parents the execution-events fan-out.
_FANOUT_PARENT = "workflow_deployments"


@dataclasses.dataclass
class VellumResumeConfig:
    # Next `offset` to request for a simple (non-fan-out) list endpoint. Seeds the OffsetPaginator's
    # resume state; saved after each fully-yielded page so a crash re-fetches the last page (merge
    # dedupes) rather than skipping it.
    offset: int = 0
    # Legacy field kept only so pre-migration saved state still parses (dataclass(**saved)). The
    # fan-out now checkpoints through `fanout_state`; an old-shape bookmark starts the fan-out fresh.
    deployment_id: str | None = None
    # Fan-out resume state (framework shape): {"completed": [child_path, ...], "current": child_path |
    # None, "child_state": {...} | None}. Skips fully-synced deployments and resumes the in-progress one.
    fanout_state: dict[str, Any] | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {"X-API-KEY": api_key, "Accept": "application/json"}


def check_credentials(api_key: str) -> tuple[bool, int | None]:
    """Probe an auth-gated list endpoint. Returns ``(reachable, status_code)``.

    ``/document-indexes`` strictly requires a key (unlike ``/workflow-deployments``, which serves
    public demo data without one), so a 200 confirms the key is genuinely valid.
    """
    url = f"{VELLUM_BASE_URL}/document-indexes"
    try:
        # capture=False: Vellum bodies can echo user-authored content (workflow inputs/outputs,
        # document metadata, descriptions) the name-based scrubbers can't recognise.
        session = make_tracked_session(redact_values=(api_key,), capture=False)
        response = session.get(url, headers=_get_headers(api_key), params={"limit": 1}, timeout=10)
        return response.status_code == 200, response.status_code
    except Exception:
        return False, None


def _list_paginator() -> OffsetPaginator:
    # Vellum list responses carry `count`/`results`; page on offset and stop once the accumulated
    # offset reaches `count` (a short final page also terminates via OffsetPaginator's built-in check).
    return OffsetPaginator(limit=PAGE_SIZE, offset_param="offset", limit_param="limit", total_path="count")


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": VELLUM_BASE_URL,
        "headers": {"Accept": "application/json"},
        "auth": {"type": "api_key", "api_key": api_key, "name": "X-API-KEY", "location": "header"},
        # capture=False: Vellum response bodies can echo user-authored content the name-based
        # scrubbers can't recognise, so they must not enter HTTP sample capture. The api_key is still
        # value-redacted (from the auth secret) in logs and raised error messages.
        "session": make_tracked_session(redact_values=(api_key,), capture=False),
    }


def _simple_resource(
    api_key: str,
    config: VellumEndpointConfig,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[VellumResumeConfig],
) -> Iterable[Any]:
    params: dict[str, Any] = {"limit": PAGE_SIZE}
    if config.ordering:
        params["ordering"] = config.ordering

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": "results",
                    "paginator": _list_paginator(),
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.offset:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(VellumResumeConfig(offset=int(state["offset"])))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _fanout_resource(
    api_key: str,
    config: VellumEndpointConfig,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[VellumResumeConfig],
) -> Iterable[Any]:
    """Fan out over every workflow deployment, pulling its execution events and stamping the parent id.

    The parent deployment id is injected into each child row under `parent_id_field` so the composite
    primary key (`[workflow_deployment_id, span_id]`) stays unique table-wide. A deployment deleted
    between enumeration and its fetch 404s — `response_actions` treats that as an empty page and skips
    it rather than failing the whole sync; any other error propagates. Single dependent resource, so
    the fan-out is resumable: fully-synced deployments are skipped and the in-progress one resumes.
    """
    parent_id_field = config.parent_id_field
    assert parent_id_field is not None, "fan-out endpoints must define parent_id_field"

    parent_config = VELLUM_ENDPOINTS[_FANOUT_PARENT]
    parent_params: dict[str, Any] = {"limit": PAGE_SIZE}
    if parent_config.ordering:
        parent_params["ordering"] = parent_config.ordering

    parent_resource: EndpointResource = {
        "name": _FANOUT_PARENT,
        "table_name": _FANOUT_PARENT,
        "write_disposition": "replace",
        "table_format": "delta",
        "endpoint": {
            "path": parent_config.path,
            "params": parent_params,
            "data_selector": "results",
            "paginator": _list_paginator(),
        },
    }

    # The resolve param name must match the `{deployment_id}` placeholder in the child path.
    child_resource: EndpointResource = {
        "name": endpoint,
        "table_name": endpoint,
        "write_disposition": "replace",
        "table_format": "delta",
        "include_from_parent": ["id"],
        "endpoint": {
            "path": config.path,
            "params": {
                "deployment_id": {"type": "resolve", "resource": _FANOUT_PARENT, "field": "id"},
                "limit": PAGE_SIZE,
            },
            "data_selector": "results",
            "paginator": _list_paginator(),
            # A deployment deleted mid-sync 404s; treat it as an empty page and move on.
            "response_actions": [{"status_code": 404, "action": "ignore"}],
        },
    }

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {},
        "resources": [parent_resource, child_resource],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state is not None:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(VellumResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    child = next(r for r in resources if r.name == endpoint)
    # include_from_parent injects the parent id under `_workflow_deployments_id`; rename it to the
    # composite-key column the child rows are expected to carry.
    return child.add_map(rename_parent_fields(_FANOUT_PARENT, {"id": parent_id_field}))


def vellum_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[VellumResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = VELLUM_ENDPOINTS[endpoint]

    if config.fan_out_over_workflow_deployments:
        resource = _fanout_resource(api_key, config, endpoint, team_id, job_id, resumable_source_manager)
    else:
        resource = _simple_resource(api_key, config, endpoint, team_id, job_id, resumable_source_manager)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
