from collections.abc import Iterator
from typing import Any, Optional

from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.lovable.settings import (
    LOVABLE_API_BASE_URL,
    LOVABLE_ENDPOINTS,
    LovableEndpointConfig,
)

API_KEY_HEADER = "Lovable-API-Key"

# Bounded connect/read timeout so a host that accepts the TCP connection but never responds can't
# hold an import worker indefinitely.
REQUEST_TIMEOUT_SECONDS = 30.0


@frozen
class LovableResumeConfig:
    """Where a resumed attempt picks the fan-out back up.

    `workspace_id`/`project_id` name the parent the checkpoint belongs to (both null for the
    account-scoped endpoint). A set `cursor` means "continue that parent's pages here"; a null one
    means the parent finished, so the walk restarts at the parent after it.
    """

    workspace_id: Optional[str] = None
    project_id: Optional[str] = None
    cursor: Optional[str] = None


@frozen
class _ParentRef:
    workspace_id: Optional[str] = None
    project_id: Optional[str] = None


def _client(api_key: str) -> RESTClient:
    return RESTClient(
        base_url=LOVABLE_API_BASE_URL,
        headers={"Accept": "application/json"},
        auth=APIKeyAuth(api_key=api_key, name=API_KEY_HEADER, location="header"),
        # Lovable-API-Key is a custom header, which `requests` does not strip on a cross-origin
        # redirect, so pin every request to the API host instead of replaying the key elsewhere.
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=REQUEST_TIMEOUT_SECONDS,
        # capture=False: workspace, project, member, and PII-label rows carry names, emails, and
        # free-text security-finding content the generic scrubber's name-based denylist won't catch.
        capture=False,
    )


def _paginator() -> JSONResponseCursorPaginator:
    return JSONResponseCursorPaginator(cursor_path="pagination.next_cursor", cursor_param="cursor")


def _path(api_version: str, config: LovableEndpointConfig, parent: _ParentRef) -> str:
    return f"/{api_version}{config.path}".format(
        workspace_id=parent.workspace_id or "",
        project_id=parent.project_id or "",
    )


def _params(config: LovableEndpointConfig, parent: _ParentRef) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": config.page_size, **config.params}
    if config.parent_id_param and parent.workspace_id:
        params[config.parent_id_param] = parent.workspace_id
    return params


def _iter_rows(client: RESTClient, path: str, params: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for page in client.paginate(path=path, params=params, paginator=_paginator(), data_selector="data"):
        yield from page


def _iter_parents(client: RESTClient, api_version: str, config: LovableEndpointConfig) -> Iterator[_ParentRef]:
    if config.scope == "account":
        yield _ParentRef()
        return

    workspaces = LOVABLE_ENDPOINTS["Workspaces"]
    for workspace in _iter_rows(
        client, _path(api_version, workspaces, _ParentRef()), _params(workspaces, _ParentRef())
    ):
        workspace_id = workspace.get("id")
        if not workspace_id:
            continue
        if config.scope == "workspace":
            yield _ParentRef(workspace_id=workspace_id)
            continue

        projects = LOVABLE_ENDPOINTS["Projects"]
        workspace_ref = _ParentRef(workspace_id=workspace_id)
        for project in _iter_rows(
            client, _path(api_version, projects, workspace_ref), _params(projects, workspace_ref)
        ):
            project_id = project.get("id")
            if project_id:
                yield _ParentRef(workspace_id=workspace_id, project_id=project_id)


def resume_position(parents: list[_ParentRef], resume: Optional[LovableResumeConfig]) -> tuple[int, Optional[str]]:
    """Index into `parents` to restart at, and the cursor to seed its first request with.

    Falls back to a full walk when the checkpointed parent is gone from the listing, because
    re-reading rows beats resuming past a parent that no longer lines up.
    """
    if resume is None:
        return 0, None

    checkpoint = _ParentRef(workspace_id=resume.workspace_id, project_id=resume.project_id)
    if checkpoint not in parents:
        return 0, None

    index = parents.index(checkpoint)
    return (index, resume.cursor) if resume.cursor else (index + 1, None)


def _with_parent_ids(row: dict[str, Any], parent: _ParentRef) -> dict[str, Any]:
    """Stamp the fan-out parent onto a child row.

    Child endpoints identify rows only within their parent (a collaborator carries a `user_id`, not
    the project), so the parent id is what makes the primary key unique across the whole table.
    """
    if parent.workspace_id:
        row.setdefault("workspace_id", parent.workspace_id)
    if parent.project_id:
        row.setdefault("project_id", parent.project_id)
    return row


def _iter_endpoint(
    client: RESTClient,
    api_version: str,
    config: LovableEndpointConfig,
    resumable_source_manager: ResumableSourceManager[LovableResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    parents = list(_iter_parents(client, api_version, config))
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_index, cursor = resume_position(parents, resume)

    for index in range(start_index, len(parents)):
        parent = parents[index]

        def save_checkpoint(state: Optional[dict[str, Any]], parent: _ParentRef = parent) -> None:
            next_cursor = state.get("cursor") if state else None
            resumable_source_manager.save_state(
                LovableResumeConfig(
                    workspace_id=parent.workspace_id,
                    project_id=parent.project_id,
                    cursor=str(next_cursor) if next_cursor else None,
                )
            )

        for page in client.paginate(
            path=_path(api_version, config, parent),
            params=_params(config, parent),
            paginator=_paginator(),
            data_selector="data",
            resume_hook=save_checkpoint,
            initial_paginator_state={"cursor": cursor} if index == start_index and cursor else None,
        ):
            if page:
                yield [_with_parent_ids(row, parent) for row in page]

        cursor = None

    # Leaving the final checkpoint behind would let a later attempt on the same job resume past
    # every parent and sync nothing.
    resumable_source_manager.clear_state()


def lovable_source(
    api_key: str,
    api_version: str,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[LovableResumeConfig],
) -> SourceResponse:
    config = LOVABLE_ENDPOINTS[endpoint]
    client = _client(api_key)

    return SourceResponse(
        name=endpoint,
        items=lambda: _iter_endpoint(client, api_version, config, resumable_source_manager),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_key: str, api_version: str) -> tuple[bool, str | None]:
    is_valid, status_code = validate_via_probe(
        # capture=False: the probe's response body carries the caller's real account/workspace
        # details, which the generic scrubber's name-based denylist won't catch.
        lambda: make_tracked_session(redact_values=(api_key,), capture=False),
        f"{LOVABLE_API_BASE_URL}/{api_version}/me",
        headers={API_KEY_HEADER: api_key},
        # The key rides a custom header, which `requests` replays across a cross-origin redirect.
        allow_redirects=False,
    )
    if is_valid:
        return True, None
    if status_code == 401:
        return False, "Invalid Lovable API key. Create a new key in Lovable and reconnect."
    return False, "Could not connect to Lovable. Check the API key and try again."


def _probe_status(client: RESTClient, path: str, params: dict[str, Any]) -> int | None:
    """Status of a single-row GET, or `None` when no response came back at all."""
    try:
        for _ in client.paginate(path=path, params=params, paginator=SinglePagePaginator(), data_selector="data"):
            break
    except HTTPError as error:
        return error.response.status_code if error.response is not None else None
    except Exception:
        return None
    return 200


def _first_id(client: RESTClient, api_version: str, config: LovableEndpointConfig, parent: _ParentRef) -> str | None:
    try:
        for row in _iter_rows(client, _path(api_version, config, parent), {**_params(config, parent), "limit": 1}):
            row_id = row.get("id")
            if row_id:
                return str(row_id)
    except Exception:
        return None
    return None


def check_endpoint_permissions(api_key: str, api_version: str, endpoints: list[str]) -> dict[str, str | None]:
    """Per-table reason the key can't read it, or `None` when it can.

    Most tables sit behind a Lovable plan tier and answer 402 below it, so probing turns a table
    that could only ever fail into one the schema picker shows as unavailable and leaves off.
    """
    client = _client(api_key)
    workspaces = LOVABLE_ENDPOINTS["Workspaces"]
    workspace_id = _first_id(client, api_version, workspaces, _ParentRef())
    # A saved schema whose endpoint left the catalog must not fail the whole schema picker.
    known = {name: LOVABLE_ENDPOINTS[name] for name in endpoints if name in LOVABLE_ENDPOINTS}
    project_id: str | None = None
    if workspace_id and any(config.scope == "project" for config in known.values()):
        project_id = _first_id(
            client, api_version, LOVABLE_ENDPOINTS["Projects"], _ParentRef(workspace_id=workspace_id)
        )

    permissions: dict[str, str | None] = dict.fromkeys(endpoints)
    for name, config in known.items():
        parent = _ParentRef(workspace_id=workspace_id, project_id=project_id)
        # No workspace or project to probe against means nothing to report, because an empty
        # account is not a permission problem.
        if (config.scope == "workspace" and not workspace_id) or (config.scope == "project" and not project_id):
            permissions[name] = None
            continue

        status = _probe_status(client, _path(api_version, config, parent), {**_params(config, parent), "limit": 1})
        if status == 402:
            plan = config.minimum_plan or "paid"
            permissions[name] = f"This table needs Lovable's {plan} plan or higher."
        elif status == 403:
            permissions[name] = "This Lovable API key does not have permission to read this table."
        else:
            permissions[name] = None
    return permissions
