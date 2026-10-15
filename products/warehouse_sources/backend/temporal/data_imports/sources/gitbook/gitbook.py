import dataclasses
from collections.abc import Callable
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
)
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
    Endpoint,
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.gitbook.settings import (
    GITBOOK_ENDPOINTS,
    GitBookEndpointConfig,
)

GITBOOK_BASE_URL = "https://api.gitbook.com/v1"
# List endpoints accept a `limit` of up to 1000 per the OpenAPI spec; a moderate page keeps
# individual payloads small (change requests and comments embed document bodies).
PAGE_SIZE = 250
# Cheap endpoint used to confirm an API token is genuine. The token inherits its owner's
# permissions, so per-endpoint access is validated lazily at sync time.
DEFAULT_PROBE_PATH = "/user"

# Every list response is `{"items": [...], "next": {"page": "..."}}`; `next` is omitted on the last
# page. The parent list of a space-, site- or team-scoped endpoint is enumerated per organization
# (orgs -> spaces/sites/teams).
_ORGS_PATH = "/orgs"
_INTERMEDIATE_PARENTS: dict[str, tuple[str, str]] = {
    "space": ("spaces", "/orgs/{parent_id}/spaces"),
    "site": ("sites", "/orgs/{parent_id}/sites"),
    "team": ("teams", "/orgs/{parent_id}/teams"),
}


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


def _format_gitbook_datetime(value: Any) -> str:
    normalized = coerce_datetime_to_utc(value)
    if normalized is None:
        return str(value)
    return normalized.strftime("%Y-%m-%dT%H:%M:%SZ")


def _flatten_pages(row: dict[str, Any]) -> list[dict[str, Any]]:
    # One row per page of the revision tree. Nested pages drop their `pages` children and record
    # their parent instead, and inherit the space id injected on the top-level row.
    space_id = row.get("space_id")
    rows: list[dict[str, Any]] = []
    stack: list[tuple[dict[str, Any], Optional[str]]] = [(row, None)]
    while stack:
        page, parent_page_id = stack.pop()
        children = page.get("pages") or []
        rows.append(
            {
                **{k: v for k, v in page.items() if k != "pages"},
                "space_id": space_id,
                "parent_page_id": parent_page_id,
            }
        )
        stack.extend((child, page.get("id")) for child in reversed(children))
    return rows


def _lift_team_member_user_id(row: dict[str, Any]) -> dict[str, Any]:
    row["user_id"] = ((row.get("organization") or {}).get("user") or {}).get("id")
    return row


_ROW_MAPS: dict[str, Callable[[dict[str, Any]], dict[str, Any] | list[dict[str, Any]]]] = {
    "pages": _flatten_pages,
    "team_members": _lift_team_member_user_id,
}


def _child_resource(
    name: str,
    child_path: str,
    parent_name: str,
    inject: dict[str, str],
    bind: Optional[dict[str, str]] = None,
    paginated: bool = True,
    data_selector: str = "items",
    row_map: Optional[Callable[[dict[str, Any]], dict[str, Any] | list[dict[str, Any]]]] = None,
    incremental: Optional[IncrementalConfig] = None,
) -> EndpointResource:
    # `bind` maps each path placeholder to the parent row field it is resolved from; `inject` maps
    # parent row fields to the columns they are copied into on every child row.
    params: dict[str, Any] = {"limit": PAGE_SIZE} if paginated else {}
    for placeholder, parent_field in (bind or {"parent_id": "id"}).items():
        params[placeholder] = {"type": "resolve", "resource": parent_name, "field": parent_field}
    endpoint: Endpoint = {
        "path": child_path,
        "params": params,
        "data_selector": data_selector,
        "data_selector_required": True,
    }
    if not paginated:
        endpoint["paginator"] = "single_page"
    if incremental is not None:
        endpoint["incremental"] = incremental
    resource: EndpointResource = {"name": name, "endpoint": endpoint}

    maps: list[Callable[[dict[str, Any]], Any]] = []
    if inject:
        # Inject the parent's fields into every row so rows from different parents stay
        # distinguishable (and usable in composite primary keys).
        resource["include_from_parent"] = list(inject)
        maps.append(rename_parent_fields(parent_name, inject))
    if row_map is not None:
        maps.append(row_map)
    if len(maps) == 1:
        resource["data_map"] = maps[0]
    elif maps:
        rename, reshape = maps
        resource["data_map"] = lambda row: reshape(rename(row))
    return resource


def _incremental_config(
    config: GitBookEndpointConfig, should_use_incremental_field: bool, incremental_field: Optional[str]
) -> Optional[IncrementalConfig]:
    if not should_use_incremental_field or not config.incremental_fields or config.incremental_param is None:
        return None
    return {
        "cursor_path": incremental_field or config.incremental_fields[0]["field"],
        "start_param": config.incremental_param,
        "initial_value": "1970-01-01T00:00:00Z",
        "convert": _format_gitbook_datetime,
    }


def gitbook_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[GitBookResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
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
        return _source_response(config, resource)

    if config.parent == "organization":
        # Single-hop fan-out (orgs -> child). One dependent resource, so the framework checkpoints
        # each parent's child pagination: a restart skips fully-synced parents and resumes the one
        # in progress at its saved cursor.
        rest_config = {
            "client": client,
            "resources": [
                _list_resource("orgs", _ORGS_PATH),
                _child_resource(
                    endpoint,
                    config.path,
                    parent_name="orgs",
                    inject={"id": config.parent_id_key} if config.parent_id_key else {},
                ),
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
        return _source_response(config, resource)

    # Space-, site- and team-scoped fan-out: a two-level chain orgs -> spaces/sites/teams -> child.
    # With more than one dependent resource the framework disables resume; a retry re-fetches and
    # the merge dedupes on the primary key.
    parent_name, parent_path = _INTERMEDIATE_PARENTS[config.parent]
    if config.parent == "space":
        intermediate = _child_resource(parent_name, parent_path, parent_name="orgs", inject={})
        bind = None
        inject = {"id": config.parent_id_key} if config.parent_id_key else {}
    else:
        # Site and team paths are nested under the organization, so the intermediate rows carry
        # the organization id for the child path to bind.
        intermediate = _child_resource(parent_name, parent_path, parent_name="orgs", inject={"id": "organization_id"})
        bind = {"organization_id": "organization_id", "parent_id": "id"}
        inject = {"organization_id": "organization_id"}
        if config.parent_id_key:
            inject["id"] = config.parent_id_key
    rest_config = {
        "client": client,
        "resources": [
            _list_resource("orgs", _ORGS_PATH),
            intermediate,
            _child_resource(
                endpoint,
                config.path,
                parent_name=parent_name,
                inject=inject,
                bind=bind,
                paginated=config.paginated,
                data_selector=config.data_selector,
                row_map=_ROW_MAPS.get(endpoint),
                incremental=_incremental_config(config, should_use_incremental_field, incremental_field),
            ),
        ],
    }
    built = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
    )
    resource = next(r for r in built if r.name == endpoint)
    return _source_response(config, resource)


def _source_response(config: GitBookEndpointConfig, resource: Any) -> SourceResponse:
    # Most objects have no stable creation timestamp, so only endpoints with one partition by it.
    return SourceResponse(
        name=config.name,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
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
