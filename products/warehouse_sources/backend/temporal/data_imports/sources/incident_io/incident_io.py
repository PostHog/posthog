import dataclasses
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.settings import (
    INCIDENT_IO_ENDPOINTS,
    IncidentIoEndpointConfig,
)

# Single global host — incident.io has no regions or per-account base paths.
INCIDENT_IO_BASE_URL = "https://api.incident.io"
VALIDATION_TIMEOUT_SECONDS = 10


@dataclasses.dataclass
class IncidentIoResumeConfig:
    next_url: str


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
    if config.paginated:
        params["page_size"] = config.page_size
    if config.sort_by:
        params["sort_by"] = config.sort_by
    if incremental_field and incremental_value:
        params[f"{incremental_field}[gte]"] = incremental_value
    return params


def _client_config(api_key: str) -> dict[str, Any]:
    # Bearer token goes through the framework auth config so it's redacted from logs and raised
    # errors; only the non-secret Accept header rides in the client headers.
    return {
        "base_url": INCIDENT_IO_BASE_URL,
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_key},
    }


def validate_credentials(api_key: str, schema_name: Optional[str] = None) -> tuple[bool, str | None]:
    """Probe the API to confirm the key is genuine.

    incident.io API keys carry granular per-resource view/list scopes, so a 403 from one
    endpoint can just mean a missing scope rather than a bad key. At source-create
    (``schema_name=None``) we accept 403 — the key authenticated, it's only missing a
    scope the user may not need. When validating a specific schema, a 403 is an error.
    """
    config = INCIDENT_IO_ENDPOINTS.get(schema_name or "", INCIDENT_IO_ENDPOINTS["incidents"])
    params: dict[str, Any] = {"page_size": 1} if config.paginated else {}

    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        _build_url(config.path, params),
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
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


def incident_io_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[IncidentIoResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = INCIDENT_IO_ENDPOINTS[endpoint]

    initial_paginator_state: Optional[dict[str, Any]] = None
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
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

    # incident.io paginates via a record-ID cursor in `pagination_meta.after`, replayed as the
    # `after` query param. Config-style endpoints return the full list in one unpaginated response.
    paginator: BasePaginator = (
        JSONResponseCursorPaginator(cursor_path="pagination_meta.after", cursor_param="after")
        if config.paginated
        else SinglePagePaginator()
    )

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": config.data_key,
                    "paginator": paginator,
                },
            }
        ],
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

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[config.primary_key],
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
