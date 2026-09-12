import dataclasses
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.asana.settings import (
    ASANA_ENDPOINTS,
    AsanaEndpointConfig,
    FanOut,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

ASANA_BASE_URL = "https://app.asana.com/api/1.0"
# Asana caps list pages at 100 items.
PAGE_SIZE = 100

# Asana list responses carry the next-page link in the body under `next_page.uri` (a self-contained
# absolute URL). A null `next_page` ends pagination.
NEXT_URL_PATH = "next_page.uri"


@dataclasses.dataclass
class AsanaResumeConfig:
    # Legacy fields from the hand-rolled fan-out. Kept (now with defaults) so state saved by the
    # previous implementation still deserializes via `ResumableSourceManager._load_json`.
    remaining_urls: list[str] = dataclasses.field(default_factory=list)
    current_url: Optional[str] = None
    # Framework paginator / fan-out resume snapshot for the current endpoint. When only the legacy
    # fields are present (old saved state) this is None and that part of the sync starts fresh —
    # a re-fetch, which the merge dedupes on `gid`.
    paginator_state: Optional[dict[str, Any]] = None


def _paginator() -> JSONResponsePaginator:
    return JSONResponsePaginator(next_url_path=NEXT_URL_PATH)


def _resource(name: str, path: str, params: dict[str, Any], *, paginated: bool = True) -> EndpointResource:
    return {
        "name": name,
        "endpoint": {
            "path": path,
            "params": params,
            "data_selector": "data",
            "paginator": _paginator() if paginated else SinglePagePaginator(),
        },
    }


@frozen
class _ParentSpec:
    """A resource fetched only to resolve gids for the endpoints that fan out over it."""

    name: str
    # Placeholder the child's path carries, bound from this parent's gid per request.
    param: str
    path: str
    # How this parent is itself reached, so a chain can be built from the deepest level up.
    fan_out: FanOut = "none"
    opt_fields: list[str] = dataclasses.field(default_factory=list)
    organizations_only: bool = False


_PARENTS: dict[FanOut, _ParentSpec] = {
    # `is_organization` is opted in so the organization-only fan-out can drop plain workspaces.
    "workspace": _ParentSpec(
        name="workspaces", param="workspace_gid", path="/workspaces", opt_fields=["is_organization"]
    ),
    "organization": _ParentSpec(
        name="workspaces",
        param="workspace_gid",
        path="/workspaces",
        opt_fields=["is_organization"],
        organizations_only=True,
    ),
    "project": _ParentSpec(
        name="projects", param="project_gid", path="/projects?workspace={workspace_gid}", fan_out="workspace"
    ),
    "task": _ParentSpec(name="tasks", param="task_gid", path="/tasks?project={project_gid}", fan_out="project"),
    "goal": _ParentSpec(name="goals", param="goal_gid", path="/goals?workspace={workspace_gid}", fan_out="workspace"),
    "user": _ParentSpec(name="users", param="user_gid", path="/users"),
}


def _resolve(spec: _ParentSpec) -> dict[str, Any]:
    return {"type": "resolve", "resource": spec.name, "field": "gid"}


def _parent_chain(fan_out: FanOut) -> list[str | EndpointResource]:
    """Every resource needed to produce the gids a `fan_out` endpoint binds, outermost first."""
    if fan_out == "none":
        return []

    spec = _PARENTS[fan_out]
    params: dict[str, Any] = {"limit": PAGE_SIZE}
    if spec.opt_fields:
        params["opt_fields"] = ",".join(spec.opt_fields)
    if spec.fan_out != "none":
        params[_PARENTS[spec.fan_out].param] = _resolve(_PARENTS[spec.fan_out])

    resource = _resource(spec.name, spec.path, params)
    if spec.organizations_only:
        # `/organizations/{gid}/...` is only valid for organization workspaces; returning [] drops
        # the row so the child fan-out never requests it.
        resource["data_map"] = lambda workspace: workspace if workspace.get("is_organization") else []

    return [*_parent_chain(spec.fan_out), resource]


def _build_resources(config: AsanaEndpointConfig) -> list[str | EndpointResource]:
    """Build the rest_source resource chain for an endpoint, fanning out over parents as needed.
    Only the last (target) resource's rows are surfaced; parents exist solely to resolve gids."""
    target_params: dict[str, Any] = {"limit": PAGE_SIZE} if config.paginated else {}
    if config.opt_fields:
        target_params["opt_fields"] = ",".join(config.opt_fields)

    if config.fan_out != "none":
        spec = _PARENTS[config.fan_out]
        target_params[spec.param] = _resolve(spec)

    target = _resource(config.name, config.path, target_params, paginated=config.paginated)
    if config.parent_fields:
        target["include_from_parent"] = list(config.parent_fields)
        target["data_map"] = rename_parent_fields(_PARENTS[config.fan_out].name, config.parent_fields)

    return [*_parent_chain(config.fan_out), target]


def asana_source(
    access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AsanaResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = ASANA_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": ASANA_BASE_URL,
            # Auth (Bearer) is supplied via the framework auth config so the token is redacted from
            # logs; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": access_token},
            "paginator": _paginator(),
        },
        "resources": _build_resources(config),
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.paginator_state is not None:
            initial_paginator_state = resume.paginator_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while there's more to fetch; the framework saves AFTER a page is yielded so a
        # crash re-yields the last page (merge dedupes on gid) rather than skipping it. Multi-level
        # (project) fan-out disables resume entirely, so this is never called for those endpoints.
        if state:
            resumable_source_manager.save_state(AsanaResumeConfig(paginator_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    target = next(resource for resource in resources if resource.name == endpoint)

    return SourceResponse(
        name=endpoint,
        items=lambda: target,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=target.column_hints,
    )


def validate_credentials(access_token: str) -> bool:
    """Confirm the personal access token is valid. /users/me needs no extra scopes."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(access_token,)),
        f"{ASANA_BASE_URL}/users/me",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    return ok
