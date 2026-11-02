from collections.abc import Iterator
from datetime import UTC, datetime, time, timedelta
from typing import Any, Optional

from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
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
    ANALYTICS_MAX_RANGE_DAYS,
    LOVABLE_API_BASE_URL,
    LOVABLE_URL_VERSION_SEGMENT,
    LovableEndpointConfig,
    version_config,
)

API_KEY_HEADER = "Lovable-API-Key"
VERSION_HEADER = "Lovable-Version"

# Bounded connect/read timeout so a host that accepts the TCP connection but never responds can't
# hold an import worker indefinitely.
REQUEST_TIMEOUT_SECONDS = 30.0


@frozen
class LovableResumeConfig:
    """Where a resumed attempt picks the fan-out back up.

    `workspace_id`/`project_id`/`scan_id` name the parent the checkpoint belongs to (all null for
    the account-scoped endpoint). A set `cursor` means "continue that parent's pages here"; a null one
    means the parent finished, so the walk restarts at the parent after it.
    """

    workspace_id: Optional[str] = None
    project_id: Optional[str] = None
    cursor: Optional[str] = None
    scan_id: Optional[str] = None


@frozen
class _ParentRef:
    workspace_id: Optional[str] = None
    project_id: Optional[str] = None
    scan_id: Optional[str] = None


def _version_headers(api_version: str) -> dict[str, str]:
    header = version_config(api_version).version_header
    return {VERSION_HEADER: header} if header else {}


def _client(api_key: str, api_version: str) -> RESTClient:
    return RESTClient(
        base_url=LOVABLE_API_BASE_URL,
        headers={"Accept": "application/json", **_version_headers(api_version)},
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


def _endpoint_paginator(config: LovableEndpointConfig) -> JSONResponseCursorPaginator | SinglePagePaginator:
    return SinglePagePaginator() if config.time_series else _paginator()


def _data_selector(config: LovableEndpointConfig) -> str:
    return "time_series" if config.time_series else "data"


def _path(config: LovableEndpointConfig, parent: _ParentRef) -> str:
    return f"/{LOVABLE_URL_VERSION_SEGMENT}{config.path}".format(
        workspace_id=parent.workspace_id or "",
        project_id=parent.project_id or "",
        scan_id=parent.scan_id or "",
    )


def _params(config: LovableEndpointConfig, parent: _ParentRef) -> dict[str, Any]:
    params: dict[str, Any] = dict(config.params) if config.time_series else {"limit": config.page_size, **config.params}
    if config.parent_id_param and parent.workspace_id:
        params[config.parent_id_param] = parent.workspace_id
    return params


def _rfc3339(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def analytics_window(should_use_incremental_field: bool, last_value: Any, now: datetime) -> dict[str, str]:
    """`starts_at`/`ends_at` for an analytics request.

    A full refresh reads the longest range the API allows. An incremental run starts at the UTC day
    of the watermark, because the newest daily bucket is still filling up when it is first read.
    """
    earliest = datetime.combine(now.date() - timedelta(days=ANALYTICS_MAX_RANGE_DAYS - 1), time.min, tzinfo=UTC)
    starts_at = earliest
    last = parse_datetime_value(last_value) if should_use_incremental_field else None
    if last is not None:
        starts_at = max(earliest, datetime.combine(last.date(), time.min, tzinfo=UTC))
    return {"starts_at": _rfc3339(starts_at), "ends_at": _rfc3339(now)}


def _time_series_rows(time_series: dict[str, Any]) -> list[dict[str, Any]]:
    """Pivot `{metric: {data: [{timestamp, value}]}}` into one row per bucket with a column per metric."""
    rows: dict[str, dict[str, Any]] = {}
    for metric, series in time_series.items():
        if not isinstance(series, dict):
            continue
        for point in series.get("data") or []:
            timestamp = point.get("timestamp")
            if timestamp:
                rows.setdefault(timestamp, {"timestamp": timestamp})[metric] = point.get("value")
    return [rows[timestamp] for timestamp in sorted(rows)]


def _iter_rows(client: RESTClient, path: str, params: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for page in client.paginate(path=path, params=params, paginator=_paginator(), data_selector="data"):
        yield from page


def _iter_parents(client: RESTClient, api_version: str, config: LovableEndpointConfig) -> Iterator[_ParentRef]:
    if config.scope == "account":
        yield _ParentRef()
        return

    endpoints = version_config(api_version).endpoints
    workspaces = endpoints["Workspaces"]
    for workspace in _iter_rows(client, _path(workspaces, _ParentRef()), _params(workspaces, _ParentRef())):
        workspace_id = workspace.get("id")
        if not workspace_id:
            continue
        if config.scope == "workspace":
            yield _ParentRef(workspace_id=workspace_id)
            continue

        projects = endpoints["Projects"]
        workspace_ref = _ParentRef(workspace_id=workspace_id)
        for project in _iter_rows(client, _path(projects, workspace_ref), _params(projects, workspace_ref)):
            project_id = project.get("id")
            if not project_id or (config.published_projects_only and not project.get("is_published")):
                continue
            project_ref = _ParentRef(workspace_id=workspace_id, project_id=project_id)
            if config.scope == "project":
                yield project_ref
                continue

            scans = endpoints["ProjectSecurityScans"]
            for scan in _iter_rows(client, _path(scans, project_ref), _params(scans, project_ref)):
                scan_id = scan.get("id")
                if scan_id:
                    yield _ParentRef(workspace_id=workspace_id, project_id=project_id, scan_id=scan_id)


def resume_position(parents: list[_ParentRef], resume: Optional[LovableResumeConfig]) -> tuple[int, Optional[str]]:
    """Index into `parents` to restart at, and the cursor to seed its first request with.

    Falls back to a full walk when the checkpointed parent is gone from the listing, because
    re-reading rows beats resuming past a parent that no longer lines up.
    """
    if resume is None:
        return 0, None

    checkpoint = _ParentRef(workspace_id=resume.workspace_id, project_id=resume.project_id, scan_id=resume.scan_id)
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
    if parent.scan_id:
        row.setdefault("scan_id", parent.scan_id)
    return row


def _iter_endpoint(
    client: RESTClient,
    api_version: str,
    config: LovableEndpointConfig,
    resumable_source_manager: ResumableSourceManager[LovableResumeConfig],
    extra_params: dict[str, Any],
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
                    scan_id=parent.scan_id,
                    cursor=str(next_cursor) if next_cursor else None,
                )
            )

        for page in client.paginate(
            path=_path(config, parent),
            params={**_params(config, parent), **extra_params},
            paginator=_endpoint_paginator(config),
            data_selector=_data_selector(config),
            data_selector_required=config.time_series,
            resume_hook=save_checkpoint,
            initial_paginator_state={"cursor": cursor} if index == start_index and cursor else None,
        ):
            rows = [row for series in page for row in _time_series_rows(series)] if config.time_series else page
            if rows:
                yield [_with_parent_ids(row, parent) for row in rows]

        cursor = None

    # Leaving the final checkpoint behind would let a later attempt on the same job resume past
    # every parent and sync nothing.
    resumable_source_manager.clear_state()


def lovable_source(
    api_key: str,
    api_version: str,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[LovableResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = version_config(api_version).endpoints[endpoint]
    client = _client(api_key, api_version)
    extra_params = (
        analytics_window(should_use_incremental_field, db_incremental_field_last_value, datetime.now(UTC))
        if config.time_series
        else {}
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: _iter_endpoint(client, api_version, config, resumable_source_manager, extra_params),
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
        f"{LOVABLE_API_BASE_URL}/{LOVABLE_URL_VERSION_SEGMENT}{version_config(api_version).probe_path}",
        headers={API_KEY_HEADER: api_key, **_version_headers(api_version)},
        # The key rides a custom header, which `requests` replays across a cross-origin redirect.
        allow_redirects=False,
    )
    if is_valid:
        return True, None
    if status_code == 401:
        return False, "Invalid Lovable API key. Create a new key in Lovable and reconnect."
    if status_code == 402:
        return False, "Lovable's API needs the Business plan or higher. Upgrade the workspace in Lovable and reconnect."
    if status_code == 403:
        return (
            False,
            "This Lovable API key can't read workspaces. Create a key with the workspaces:read scope and reconnect.",
        )
    return False, "Could not connect to Lovable. Check the API key and try again."


def _probe_status(client: RESTClient, path: str, params: dict[str, Any], data_selector: str) -> int | None:
    """Status of a single-row GET, or `None` when no response came back at all."""
    try:
        for _ in client.paginate(
            path=path, params=params, paginator=SinglePagePaginator(), data_selector=data_selector
        ):
            break
    except HTTPError as error:
        return error.response.status_code if error.response is not None else None
    except Exception:
        return None
    return 200


def _first_id(client: RESTClient, config: LovableEndpointConfig, parent: _ParentRef) -> str | None:
    try:
        for row in _iter_rows(client, _path(config, parent), {**_params(config, parent), "limit": 1}):
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
    client = _client(api_key, api_version)
    catalog = version_config(api_version).endpoints
    workspace_id = _first_id(client, catalog["Workspaces"], _ParentRef())
    # A saved schema whose endpoint left the catalog must not fail the whole schema picker.
    known = {name: catalog[name] for name in endpoints if name in catalog}
    project_id: str | None = None
    if workspace_id and any(config.scope in ("project", "scan") for config in known.values()):
        project_id = _first_id(client, catalog["Projects"], _ParentRef(workspace_id=workspace_id))
    scan_id: str | None = None
    if project_id and any(config.scope == "scan" for config in known.values()):
        scan_id = _first_id(
            client, catalog["ProjectSecurityScans"], _ParentRef(workspace_id=workspace_id, project_id=project_id)
        )

    permissions: dict[str, str | None] = dict.fromkeys(endpoints)
    now = datetime.now(UTC)
    for name, config in known.items():
        parent = _ParentRef(workspace_id=workspace_id, project_id=project_id, scan_id=scan_id)
        # No parent to probe against means nothing to report, because an empty account is not a
        # permission problem.
        if (
            (config.scope == "workspace" and not workspace_id)
            or (config.scope == "project" and not project_id)
            or (config.scope == "scan" and not scan_id)
        ):
            permissions[name] = None
            continue

        probe_params = (
            {"starts_at": _rfc3339(now - timedelta(days=1)), "ends_at": _rfc3339(now)}
            if config.time_series
            else {"limit": 1}
        )
        status = _probe_status(
            client, _path(config, parent), {**_params(config, parent), **probe_params}, _data_selector(config)
        )
        if status == 402:
            plan = config.minimum_plan or "paid"
            permissions[name] = f"This table needs Lovable's {plan} plan or higher."
        elif status == 403:
            permissions[name] = "This Lovable API key does not have permission to read this table."
        else:
            permissions[name] = None
    return permissions
