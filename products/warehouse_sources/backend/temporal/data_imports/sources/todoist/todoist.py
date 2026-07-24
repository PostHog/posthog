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
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.todoist.settings import (
    TODOIST_BASE_URL,
    TODOIST_ENDPOINTS,
    TodoistEndpointConfig,
)

# Todoist caps list endpoints at 200 items per page. The cursor paginator follows `next_cursor`
# regardless, so an over-large value would only ever cost an extra round trip if the cap were lower.
PAGE_LIMIT = 200


@dataclasses.dataclass
class TodoistResumeConfig:
    # Body cursor for the next page of a standard (non-fan-out) endpoint. None means "start at page one".
    next_cursor: str | None = None
    # Legacy field from the hand-rolled fan-out bookmark, kept so state saved by an older build still
    # parses (ResumableSourceManager does dataclass(**saved)). No longer written.
    project_id: str | None = None
    # Framework fan-out resume state for the collaborators endpoint:
    # {"completed": [child_path, ...], "current": child_path | None, "child_state": {"cursor": ...} | None}.
    fanout_state: dict | None = None


def _non_secret_headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so the token is redacted out of logs
    # and raised error messages; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


def _cursor_paginator() -> JSONResponseCursorPaginator:
    # Todoist's unified v1 API wraps lists as {"results": [...], "next_cursor": "..."} and advances
    # via the `cursor` query param.
    return JSONResponseCursorPaginator(cursor_path="next_cursor", cursor_param="cursor")


def _rename_project_id(row: dict[str, Any]) -> dict[str, Any]:
    # `include_from_parent=["id"]` injects the owning project's id as `_projects_id`; expose it as
    # `project_id` so the composite primary key [project_id, id] matches the pre-migration row shape.
    if "_projects_id" in row:
        row["project_id"] = row.pop("_projects_id")
    return row


def _source_response(endpoint: str, config: TodoistEndpointConfig, items: Any) -> SourceResponse:
    return SourceResponse(
        name=endpoint,
        items=lambda: items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def _list_source(
    api_token: str,
    endpoint: str,
    config: TodoistEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TodoistResumeConfig],
) -> SourceResponse:
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": TODOIST_BASE_URL,
            "headers": _non_secret_headers(),
            "auth": {"type": "bearer", "token": api_token},
            "paginator": _cursor_paginator(),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"limit": PAGE_LIMIT},
                    "data_selector": "results",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_cursor:
            initial_paginator_state = {"cursor": resume.next_cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(TodoistResumeConfig(next_cursor=state["cursor"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # every Todoist v1 endpoint is full refresh — no server-side incremental filter
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return _source_response(endpoint, config, resource)


def _collaborators_source(
    api_token: str,
    endpoint: str,
    config: TodoistEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TodoistResumeConfig],
) -> SourceResponse:
    """Fan out over every project, materializing project<->collaborator membership.

    Each collaborator row gets the owning `project_id` injected so the composite primary key
    [project_id, id] stays unique table-wide. Full refresh only — re-pulled rows on resume are
    deduped by the primary key on merge.
    """
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": TODOIST_BASE_URL,
            "headers": _non_secret_headers(),
            "auth": {"type": "bearer", "token": api_token},
            "paginator": _cursor_paginator(),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": "projects",
                "endpoint": {
                    "path": TODOIST_ENDPOINTS["projects"].path,
                    "params": {"limit": PAGE_LIMIT},
                    "data_selector": "results",
                },
            },
            {
                "name": endpoint,
                "include_from_parent": ["id"],
                "endpoint": {
                    "path": config.path,
                    "params": {
                        "project_id": {"type": "resolve", "resource": "projects", "field": "id"},
                        "limit": PAGE_LIMIT,
                    },
                    "data_selector": "results",
                    # A project deleted between enumeration and this fetch 404s. Treat it as an empty
                    # page and move on rather than failing the whole sync — the membership is gone.
                    "response_actions": [{"status_code": 404, "action": "ignore"}],
                },
                "data_map": _rename_project_id,
            },
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        resumable_source_manager.save_state(TodoistResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    child = next(resource for resource in resources if resource.name == endpoint)
    return _source_response(endpoint, config, child)


def todoist_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TodoistResumeConfig],
) -> SourceResponse:
    config = TODOIST_ENDPOINTS[endpoint]
    if config.fan_out_over_projects:
        return _collaborators_source(api_token, endpoint, config, team_id, job_id, resumable_source_manager)
    return _list_source(api_token, endpoint, config, team_id, job_id, resumable_source_manager)


def validate_credentials(api_token: str) -> bool:
    # Cheapest authenticated probe: pull a single project. A genuine token returns 200; a bad/revoked
    # one returns 401. validate_via_probe swallows transport errors and maps them to "not validated".
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{TODOIST_BASE_URL}/projects?limit=1",
        headers={"Authorization": f"Bearer {api_token}", **_non_secret_headers()},
    )
    return ok


__all__ = ["TodoistResumeConfig", "todoist_source", "validate_credentials"]
