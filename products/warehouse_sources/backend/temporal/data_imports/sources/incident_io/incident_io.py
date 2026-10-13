import dataclasses
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional, cast
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.settings import (
    EntryWindow,
    IncidentIoEndpointConfig,
    endpoints_for_version,
)

# Single global host — incident.io has no regions or per-account base paths.
INCIDENT_IO_BASE_URL = "https://api.incident.io"
VALIDATION_TIMEOUT_SECONDS = 10


@dataclasses.dataclass(frozen=True)
class IncidentIoResumeConfig:
    next_url: Optional[str] = None
    # Framework fan-out resume state for the parent-scoped endpoints, opaque to this source and
    # passed straight back to the fan-out helper.
    fanout_state: Optional[dict[str, Any]] = None
    # The window a windowed fan-out started with. Its cursor is only valid against that window's end.
    window_params: Optional[dict[str, str]] = None


def _build_url(path: str, params: dict[str, Any]) -> str:
    clean_params = {key: value for key, value in params.items() if value is not None}
    if not clean_params:
        return f"{INCIDENT_IO_BASE_URL}{path}"
    return f"{INCIDENT_IO_BASE_URL}{path}?{urlencode(clean_params)}"


def _params_from_url(url: str) -> dict[str, str]:
    """Recover the query params of a saved next-page URL, minus the page cursor.

    On resume we keep the original chain's filters instead of rebuilding them from the
    (possibly advanced) incremental watermark — mixing a fresh `gte` filter with an old
    `after` cursor could skip rows the cursor hadn't reached yet.
    """
    params = dict(parse_qsl(urlsplit(url).query))
    params.pop("after", None)
    return params


def _after_from_url(url: str) -> Optional[str]:
    return dict(parse_qsl(urlsplit(url).query)).get("after")


def _format_filter_value(value: Any) -> Optional[str]:
    """Coerce an incremental cursor value to a date string for incident.io `[gte]` filters.

    The API docs only show date-formatted filter values (e.g. `2024-05-01`), so we
    conservatively truncate to a date. `gte` is inclusive and we merge on `id`, so the
    up-to-a-day overlap is deduped downstream.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            return None
    return None


def _build_params(
    config: IncidentIoEndpointConfig,
    incremental_field: Optional[str],
    incremental_value: Optional[str],
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if config.paginated and config.page_size_param:
        params[config.page_size_param] = config.page_size
    if config.sort_by:
        params["sort_by"] = config.sort_by
    if incremental_field and incremental_value:
        params[f"{incremental_field}[gte]"] = incremental_value
    return params


def _window_params(window: EntryWindow, now: datetime) -> dict[str, str]:
    return {
        window.start_param: (now - window.lookback).strftime("%Y-%m-%dT%H:%M:%SZ"),
        window.end_param: (now + window.lookahead).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _drop_fields(fields: tuple[str, ...]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _mapper(row: dict[str, Any]) -> dict[str, Any]:
        for name in fields:
            row.pop(name, None)
        return row

    return _mapper


def _client_config(api_key: str, capture: bool = True) -> ClientConfig:
    # Bearer token goes through the framework auth config so it's redacted from logs and raised
    # errors; only the non-secret Accept header rides in the client headers.
    return {
        "base_url": INCIDENT_IO_BASE_URL,
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_key},
        "capture": capture,
    }


def _probe_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


def _fanout_child_probe_url(
    api_key: str, endpoints: dict[str, IncidentIoEndpointConfig], config: IncidentIoEndpointConfig
) -> Optional[str]:
    """Build a one-row child request bound to a real parent id, or None when there is no parent row.

    A fan-out child can have its own scope (catalog entries need `catalog_entries.view`, separate
    from `catalog_types.view`), so probing only the parent can pass a key that can't sync the child.
    """
    assert config.fanout is not None
    parent = endpoints[config.fanout.parent_name]
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            _build_url(parent.path, {}), headers=_probe_headers(api_key), timeout=VALIDATION_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        rows = response.json().get(parent.data_key) or []
    except Exception:
        return None
    if not rows:
        return None
    parent_id = quote(str(rows[0][config.fanout.resolve_field]), safe="")
    path = config.path.replace(f"{{{config.fanout.resolve_param}}}", parent_id)
    if config.page_size_param is None:
        return f"{INCIDENT_IO_BASE_URL}{path}"
    return f"{INCIDENT_IO_BASE_URL}{path}&{urlencode({config.page_size_param: 1})}"


def _probe_result(api_key: str, url: str, schema_name: Optional[str]) -> tuple[bool, str | None]:
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        url,
        headers=_probe_headers(api_key),
        timeout=VALIDATION_TIMEOUT_SECONDS,
    )

    if status is None:
        return False, "Unable to reach the incident.io API. Please try again."

    if status == 401:
        return False, "incident.io authentication failed. Please check that your API key is valid."

    if status == 403:
        if schema_name is None:
            return True, None
        return (
            False,
            f"Your incident.io API key can't list {schema_name}. incident.io API keys have per-resource permissions — grant the key the 'view' scope for this resource and try again.",
        )

    if status < 400:
        return True, None

    return False, f"incident.io API returned an unexpected response (status {status})."


def validate_credentials(api_key: str, api_version: str, schema_name: Optional[str] = None) -> tuple[bool, str | None]:
    """Probe the API to confirm the key is genuine.

    incident.io API keys carry granular per-resource view/list scopes, so a 403 from one
    endpoint can just mean a missing scope rather than a bad key. At source-create
    (``schema_name=None``) we accept 403 — the key authenticated, it's only missing a
    scope the user may not need. When validating a specific schema, a 403 is an error.
    """
    endpoints = endpoints_for_version(api_version)
    config = endpoints.get(schema_name or "", endpoints["incidents"])
    # A fan-out child can't be listed without a parent id, so the parent list is probed first.
    probe_config = endpoints[config.fanout.parent_name] if config.fanout is not None else config
    params: dict[str, Any] = (
        {probe_config.page_size_param: 1} if probe_config.paginated and probe_config.page_size_param else {}
    )

    is_valid, error = _probe_result(api_key, _build_url(probe_config.path, params), schema_name)
    if not is_valid or config.fanout is None:
        return is_valid, error

    child_url = _fanout_child_probe_url(api_key, endpoints, config)
    if child_url is None:
        return True, None
    return _probe_result(api_key, child_url, schema_name)


def _paginator(config: IncidentIoEndpointConfig) -> BasePaginator:
    # incident.io paginates via a cursor in `pagination_meta.after`, replayed as the endpoint's
    # cursor param (`after` for most lists). Config-style endpoints return the full list in one
    # unpaginated response.
    return (
        JSONResponseCursorPaginator(cursor_path="pagination_meta.after", cursor_param=config.cursor_param)
        if config.paginated
        else SinglePagePaginator()
    )


def _source_response(config: IncidentIoEndpointConfig, items: Iterable[Any]) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=lambda: items,
        primary_keys=config.primary_keys,
        # Incidents are requested with `sort_by=created_at_oldest_first` (the only sortable
        # endpoint). When syncing incrementally on `updated_at`, values within a run aren't
        # monotonic — the final watermark is still correct because a run fetches every row
        # matching the filter, and merge-on-id dedupes any overlap on the next run.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def _fanout_source(
    api_key: str,
    endpoints: dict[str, IncidentIoEndpointConfig],
    config: IncidentIoEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[IncidentIoResumeConfig],
) -> SourceResponse:
    """Fetch a parent-scoped endpoint once per row of its parent lookup list."""
    assert config.fanout is not None
    parent_config = endpoints[config.fanout.parent_name]

    initial_paginator_state: Optional[dict[str, Any]] = None
    window_params: Optional[dict[str, str]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state:
            initial_paginator_state = resume.fanout_state
            window_params = resume.window_params
    if config.entry_window is not None and window_params is None:
        window_params = _window_params(config.entry_window, datetime.now(UTC))

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        resumable_source_manager.save_state(IncidentIoResumeConfig(fanout_state=state, window_params=window_params))

    child_params: dict[str, Any] = {}
    if config.page_size_param:
        child_params[config.page_size_param] = config.page_size
    if window_params:
        child_params.update(window_params)

    resource = cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=endpoints,
            child_endpoint=config.name,
            fanout=config.fanout,
            client_config=_client_config(api_key),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            # Parent page sizes ride in each fan-out's `parent_params`, since some parent lookup
            # lists are unpaginated and take no page-size param.
            page_size_param=None,
            child_params_extra=child_params,
            parent_endpoint_extra={"paginator": _paginator(parent_config), "data_selector": parent_config.data_key},
            child_endpoint_extra={"paginator": _paginator(config), "data_selector": config.data_key},
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        ),
    )
    return _source_response(config, resource)


def incident_io_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[IncidentIoResumeConfig],
    api_version: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoints = endpoints_for_version(api_version)
    config = endpoints[endpoint]
    if config.fanout is not None:
        return _fanout_source(api_key, endpoints, config, team_id, job_id, resumable_source_manager)

    initial_paginator_state: Optional[dict[str, Any]] = None
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_url:
        # Preserve the interrupted chain's filters and cursor verbatim — never recompute the
        # `gte` filter from a possibly-advanced watermark against an old `after` cursor.
        params: dict[str, Any] = _params_from_url(resume.next_url)
        after = _after_from_url(resume.next_url)
        if after is not None:
            initial_paginator_state = {"cursor": after}
    else:
        incremental_value = (
            _format_filter_value(db_incremental_field_last_value) if should_use_incremental_field else None
        )
        params = _build_params(config, incremental_field if should_use_incremental_field else None, incremental_value)

    resource_config: EndpointResource = {
        "name": endpoint,
        "endpoint": {
            "path": config.path,
            "params": params,
            "data_selector": config.data_key,
            "paginator": _paginator(config),
        },
    }
    if config.excluded_fields:
        resource_config["data_map"] = _drop_fields(config.excluded_fields)

    rest_config: RESTAPIConfig = {
        # Excluded fields are dropped from rows only after HTTP sample capture saw the raw body.
        "client": _client_config(api_key, capture=not config.excluded_fields),
        "resources": [resource_config],
    }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on id) rather than skipping it. The saved URL keeps the
        # run's filters so resume replays the exact same chain with the next cursor.
        if state and state.get("cursor"):
            url = _build_url(config.path, {**params, "after": state["cursor"]})
            resumable_source_manager.save_state(IncidentIoResumeConfig(next_url=url))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return _source_response(config, resource)
