import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.asana.settings import (
    ASANA_ENDPOINTS,
    PRIMARY_KEY,
    AsanaEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

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


def _resource(name: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "endpoint": {
            "path": path,
            "params": params,
            "data_selector": "data",
            "paginator": _paginator(),
        },
    }


def _workspaces_parent(*, filter_organizations: bool) -> dict[str, Any]:
    """Workspaces list used only to resolve child gids. `is_organization` is opted in so the
    organization-only fan-out (teams) can drop non-organization workspaces."""
    resource = _resource("workspaces", "/workspaces", {"limit": PAGE_SIZE, "opt_fields": "is_organization"})
    if filter_organizations:
        # `/organizations/{gid}/teams` is only valid for organization workspaces; returning [] drops
        # the row so the child fan-out never requests it.
        resource["data_map"] = lambda workspace: workspace if workspace.get("is_organization") else []
    return resource


def _projects_parent() -> dict[str, Any]:
    """Projects list (one request per workspace) used only to resolve project gids for the
    project-level fan-out (tasks, sections)."""
    return _resource(
        "projects",
        "/projects?workspace={workspace_gid}",
        {"limit": PAGE_SIZE, "workspace_gid": {"type": "resolve", "resource": "workspaces", "field": "gid"}},
    )


def _build_resources(config: AsanaEndpointConfig) -> list[dict[str, Any]]:
    """Build the rest_source resource chain for an endpoint, fanning out over parents as needed.
    Only the last (target) resource's rows are surfaced; parents exist solely to resolve gids."""
    target_params: dict[str, Any] = {"limit": PAGE_SIZE}
    if config.opt_fields:
        target_params["opt_fields"] = ",".join(config.opt_fields)

    if config.fan_out == "none":
        return [_resource(config.name, config.path, target_params)]

    if config.fan_out in ("workspace", "organization"):
        target_params["workspace_gid"] = {"type": "resolve", "resource": "workspaces", "field": "gid"}
        return [
            _workspaces_parent(filter_organizations=config.fan_out == "organization"),
            _resource(config.name, config.path, target_params),
        ]

    if config.fan_out == "project":
        target_params["project_gid"] = {"type": "resolve", "resource": "projects", "field": "gid"}
        return [
            _workspaces_parent(filter_organizations=False),
            _projects_parent(),
            _resource(config.name, config.path, target_params),
        ]

    raise ValueError(f"Unknown fan_out mode: {config.fan_out}")


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
        primary_keys=[PRIMARY_KEY],
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
