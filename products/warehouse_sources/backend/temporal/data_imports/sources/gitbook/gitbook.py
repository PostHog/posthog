import dataclasses
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
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.gitbook.settings import GITBOOK_ENDPOINTS

GITBOOK_BASE_URL = "https://api.gitbook.com/v1"
# List endpoints accept a `limit` of up to 1000 per the OpenAPI spec; a moderate page keeps
# individual payloads small (change requests and comments embed document bodies).
PAGE_SIZE = 250
# Cheap endpoint used to confirm an API token is genuine. The token inherits its owner's
# permissions, so per-endpoint access is validated lazily at sync time.
DEFAULT_PROBE_PATH = "/user"

# Every list response is `{"items": [...], "next": {"page": "..."}}`; `next` is omitted on the last
# page. The parent list of a space-scoped endpoint is enumerated per organization (orgs -> spaces).
_ORGS_PATH = "/orgs"
_SPACES_PATH = "/orgs/{parent_id}/spaces"


@dataclasses.dataclass
class GitBookResumeConfig:
    # Legacy fan-out checkpoint fields, retained so pre-migration saved state still parses. The
    # framework now owns fan-out resume via `fanout_state`; these are only read for the top-level
    # `organizations` cursor (`next_page`) and are otherwise left at their defaults.
    completed_parent_ids: list[str] = dataclasses.field(default_factory=list)
    current_parent_id: Optional[str] = None
    # Opaque `next.page` token for the next page of the top-level `organizations` list.
    next_page: Optional[str] = None
    # Framework fan-out resume snapshot for single-hop endpoints:
    # `{"completed": [child_path, ...], "current": child_path | None, "child_state": {...} | None}`.
    fanout_state: Optional[dict[str, Any]] = None


def _auth_headers(api_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_token}", "Accept": "application/json"}


def _paginator() -> JSONResponseCursorPaginator:
    return JSONResponseCursorPaginator(cursor_path="next.page", cursor_param="page")


def _client_config(api_token: str) -> ClientConfig:
    return {
        "base_url": GITBOOK_BASE_URL,
        # Bearer auth goes through the framework auth config so the token is redacted from logs and
        # raised error messages; only the non-secret Accept header is set here.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_token},
        "paginator": _paginator(),
        # GitBook returns opaque page tokens (never full URLs), so every request stays on the API
        # host; pin pagination/resume to it and reject anything off-host defensively.
        "allowed_hosts": [],
    }


def _list_resource(name: str, path: str) -> EndpointResource:
    return {
        "name": name,
        "endpoint": {
            "path": path,
            "params": {"limit": PAGE_SIZE},
            "data_selector": "items",
            # A 200 body that isn't `{"items": [...]}` means the response shape changed — fail loud
            # instead of silently syncing 0 rows.
            "data_selector_required": True,
        },
    }


def _child_resource(name: str, child_path: str, parent_name: str, inject_as: Optional[str]) -> EndpointResource:
    resource: EndpointResource = {
        "name": name,
        "endpoint": {
            "path": child_path,
            "params": {
                "limit": PAGE_SIZE,
                "parent_id": {"type": "resolve", "resource": parent_name, "field": "id"},
            },
            "data_selector": "items",
            "data_selector_required": True,
        },
    }
    if inject_as is not None:
        # Inject the parent's id into every row so rows from different parents stay distinguishable
        # (and usable in composite primary keys), matching the old `parent_id_key` behavior.
        resource["include_from_parent"] = ["id"]
        resource["data_map"] = rename_parent_fields(parent_name, {"id": inject_as})
    return resource


def gitbook_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[GitBookResumeConfig],
) -> SourceResponse:
    config = GITBOOK_ENDPOINTS[endpoint]
    client = _client_config(api_token)

    if config.parent is None:
        # Top-level list (organizations): a single non-dependent resource with full cursor resume.
        rest_config: RESTAPIConfig = {"client": client, "resources": [_list_resource(endpoint, config.path)]}

        initial_state: Optional[dict[str, Any]] = None
        if resumable_source_manager.can_resume():
            resume = resumable_source_manager.load_state()
            if resume is not None and resume.next_page:
                initial_state = {"cursor": resume.next_page}

        def save_cursor(state: Optional[dict[str, Any]]) -> None:
            # Save AFTER yielding a page so a crash re-fetches from the next page (merge dedupes the
            # re-pulled page on the primary key); only persist while a next page remains.
            if state and state.get("cursor"):
                resumable_source_manager.save_state(GitBookResumeConfig(next_page=state["cursor"]))

        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            None,
            resume_hook=save_cursor,
            initial_paginator_state=initial_state,
        )
        return _source_response(endpoint, config.primary_keys, resource)

    if config.parent == "organization":
        # Single-hop fan-out (orgs -> child). One dependent resource, so the framework checkpoints
        # each parent's child pagination: a restart skips fully-synced parents and resumes the one
        # in progress at its saved cursor.
        rest_config = {
            "client": client,
            "resources": [
                _list_resource("orgs", _ORGS_PATH),
                _child_resource(endpoint, config.path, parent_name="orgs", inject_as=config.parent_id_key),
            ],
        }

        fanout_initial: Optional[dict[str, Any]] = None
        if resumable_source_manager.can_resume():
            resume = resumable_source_manager.load_state()
            if resume is not None and resume.fanout_state:
                fanout_initial = resume.fanout_state

        def save_fanout(state: Optional[dict[str, Any]]) -> None:
            if state is not None:
                resumable_source_manager.save_state(GitBookResumeConfig(fanout_state=state))

        built = rest_api_resources(
            rest_config,
            team_id,
            job_id,
            None,
            resume_hook=save_fanout,
            initial_paginator_state=fanout_initial,
        )
        resource = next(r for r in built if r.name == endpoint)
        return _source_response(endpoint, config.primary_keys, resource)

    # Space-scoped fan-out (comments): a two-level chain orgs -> spaces -> comments. With more than
    # one dependent resource the framework disables resume; a retry re-fetches and the merge dedupes
    # on the primary key.
    rest_config = {
        "client": client,
        "resources": [
            _list_resource("orgs", _ORGS_PATH),
            _child_resource("spaces", _SPACES_PATH, parent_name="orgs", inject_as=None),
            _child_resource(endpoint, config.path, parent_name="spaces", inject_as=config.parent_id_key),
        ],
    }
    built = rest_api_resources(rest_config, team_id, job_id, None)
    resource = next(r for r in built if r.name == endpoint)
    return _source_response(endpoint, config.primary_keys, resource)


def _source_response(endpoint: str, primary_keys: list[str], resource: Any) -> SourceResponse:
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=primary_keys,
        # No stable creation timestamp exists on every object, so we don't partition by datetime.
        partition_count=1,
        partition_size=1,
    )


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    # A single probe of `/user` confirms the token is genuine; per-endpoint access follows the token
    # owner's permissions and is surfaced at sync time via get_non_retryable_errors.
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{GITBOOK_BASE_URL}{DEFAULT_PROBE_PATH}",
        headers=_auth_headers(api_token),
    )
    if ok:
        return True, None
    # GitBook answers 401 for an invalid token and 403 for a missing/unauthorized one.
    if status in (401, 403):
        return False, "Invalid GitBook API token"
    if status is not None:
        return False, f"GitBook returned HTTP {status}"
    return False, "Could not validate GitBook API token"
