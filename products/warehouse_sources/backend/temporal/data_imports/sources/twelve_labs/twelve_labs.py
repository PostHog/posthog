import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    AuthConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.twelve_labs.settings import (
    TWELVE_LABS_ENDPOINTS,
    TwelveLabsEndpointConfig,
)

TWELVE_LABS_BASE_URL = "https://api.twelvelabs.io/v1.3"

# Max page size the API allows; larger values are rejected.
PAGE_LIMIT = 50

# The internal parent resource that drives the videos fan-out. include_from_parent lands the parent
# index id under `_{name}__id` (the `_id` field starts with an underscore), which the child data_map
# renames to the composite `index_id` primary-key column.
_INDEXES_PARENT_NAME = "indexes_list"
_PARENT_INDEX_ID_KEY = f"_{_INDEXES_PARENT_NAME}__id"

# Twelve Labs list endpoints paginate with page/page_limit and report the page count as
# page_info.total_page, so termination stops after the last page instead of paying an extra request.
_TOTAL_PAGE_PATH = "page_info.total_page"


@dataclasses.dataclass
class TwelveLabsResumeConfig:
    # Next page number to request (1-based). None means "start at page 1". Used by the top-level
    # (non-fan-out) endpoints.
    next_page: int | None = None
    # Legacy fan-out bookmark (id of the index being processed). Kept only so previously saved state
    # still parses (`ResumableSourceManager._load_json` does `dataclass(**saved)`); the framework
    # fan-out now checkpoints into `fanout_state`, and an old-shape bookmark restarts the fan-out
    # from scratch (merge dedupes the re-pulled rows on the [index_id, _id] key).
    index_id: str | None = None
    # Framework fan-out checkpoint: {"completed": [child_path, ...], "current": child_path | None,
    # "child_state": {"page": N} | None}.
    fanout_state: dict | None = None


def _auth_config(api_key: str) -> AuthConfig:
    # Framework auth (not a hand-built header) so the key is redacted from logs/captured samples and
    # scrubbed out of any raised error message.
    return {"type": "api_key", "api_key": api_key, "name": "x-api-key", "location": "header"}


def _get_headers(api_key: str) -> dict[str, str]:
    return {"x-api-key": api_key, "Accept": "application/json"}


def _build_url(path: str, params: dict[str, Any]) -> str:
    return f"{TWELVE_LABS_BASE_URL}{path}?{urlencode(params)}"


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor as an RFC 3339 timestamp with a Z suffix."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return str(value)


def _build_params(
    config: TwelveLabsEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    """Build the static query params for a list request (page is injected by the paginator).

    Page-number pagination means the `created_at` / `updated_at` filter can be applied on every
    page (unlike cursor APIs that only window the first page), so incremental syncs stay bounded
    without any client-side watermark termination.
    """
    params: dict[str, Any] = {"page_limit": PAGE_LIMIT}

    # `sort_by` defaults to the endpoint's advertised cursor field but always honors the user's
    # selection. Ascending sort makes the pipeline watermark advance correctly (sort_mode="asc").
    filter_field = incremental_field or (config.incremental_fields[0]["field"] if config.incremental_fields else None)

    if should_use_incremental_field and filter_field:
        params["sort_by"] = filter_field
        params["sort_option"] = "asc"
        if db_incremental_field_last_value:
            # `created_at` / `updated_at` filter at-or-after the given value; the boundary row is
            # re-fetched each sync and merge dedupes it on the primary key.
            params[filter_field] = _format_incremental_value(db_incremental_field_last_value)
    else:
        # Full refresh: sort ascending on the stable creation field so page boundaries don't skip
        # or duplicate rows if the library grows mid-sync.
        params["sort_by"] = config.partition_key or "created_at"
        params["sort_option"] = "asc"

    return params


def _paginator() -> PageNumberPaginator:
    return PageNumberPaginator(base_page=1, page_param="page", total_path=_TOTAL_PAGE_PATH)


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    """Probe /indexes to confirm the API key is genuine.

    Returns ``(ok, status_code)``. ``status_code`` is ``None`` on a transport error so the caller
    can tell a rejected key (401/403) apart from a transient outage (429/5xx/network) and avoid
    reporting a valid key as invalid during a rate-limit or downtime window.
    """
    # Redact the key from tracked telemetry and refuse redirects so a 30x can never replay the
    # `x-api-key` header to another origin.
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,), allow_redirects=False),
        _build_url("/indexes", {"page": 1, "page_limit": 1}),
        headers=_get_headers(api_key),
    )


def _top_level_resource(
    config: TwelveLabsEndpointConfig,
    api_key: str,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[TwelveLabsResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    incremental_field: str | None,
) -> Resource:
    params = _build_params(config, should_use_incremental_field, db_incremental_field_last_value, incremental_field)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": TWELVE_LABS_BASE_URL,
            "headers": {"Accept": "application/json"},
            "auth": _auth_config(api_key),
            "paginator": _paginator(),
            # Refuse redirects so a 30x can't replay the `x-api-key` header to another origin.
            "allow_redirects": False,
        },
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": "data",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if manager.can_resume():
        resume = manager.load_state()
        # Only a top-level checkpoint (no fan-out state) seeds the paginator.
        if resume is not None and resume.next_page and resume.fanout_state is None:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the hook fires AFTER a page is yielded, so a crash
        # re-fetches the last checkpointed page (merge dedupes) rather than skipping rows.
        if state and state.get("page") is not None:
            manager.save_state(TwelveLabsResumeConfig(next_page=int(state["page"])))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _fan_out_resource(
    config: TwelveLabsEndpointConfig,
    api_key: str,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[TwelveLabsResumeConfig],
) -> Resource:
    """Fan out over every index, yielding that index's videos with the parent ``index_id`` injected.

    The [index_id, _id] primary key keeps rows unique table-wide, so videos from different indexes
    never collide and merge dedupes cleanly.
    """
    child_params = _build_params(config, False, None, None)

    def _inject_index_id(row: dict[str, Any]) -> dict[str, Any]:
        # include_from_parent lands the parent index id under the mangled key; expose it under the
        # plain `index_id` column exactly as the hand-rolled source produced (`{**row, "index_id": ...}`).
        row["index_id"] = row.pop(_PARENT_INDEX_ID_KEY)
        return row

    parent_resource: EndpointResource = {
        "name": _INDEXES_PARENT_NAME,
        "endpoint": {
            "path": "/indexes",
            "params": {"page_limit": PAGE_LIMIT},
            "paginator": _paginator(),
            "data_selector": "data",
        },
    }
    child_resource: EndpointResource = {
        "name": config.name,
        "include_from_parent": ["_id"],
        "data_map": _inject_index_id,
        "endpoint": {
            "path": config.path,
            "params": {
                "index_id": {"type": "resolve", "resource": _INDEXES_PARENT_NAME, "field": "_id"},
                **child_params,
            },
            "paginator": _paginator(),
            "data_selector": "data",
        },
    }

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": TWELVE_LABS_BASE_URL,
            "headers": {"Accept": "application/json"},
            "auth": _auth_config(api_key),
            "allow_redirects": False,
        },
        "resources": [parent_resource, child_resource],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if manager.can_resume():
        resume = manager.load_state()
        # An old-shape bookmark (`index_id`) can't seed the framework fan-out — start that part
        # fresh and let merge dedupe the re-pulled rows.
        if resume is not None and resume.fanout_state is not None:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            manager.save_state(TwelveLabsResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return next(resource for resource in resources if resource.name == config.name)


def twelve_labs_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TwelveLabsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = TWELVE_LABS_ENDPOINTS[endpoint]

    if config.fan_out_over_indexes:
        resource = _fan_out_resource(config, api_key, team_id, job_id, resumable_source_manager)
    else:
        resource = _top_level_resource(
            config,
            api_key,
            team_id,
            job_id,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
            incremental_field,
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # Every list endpoint is requested with sort_option=asc, so rows arrive oldest-first and the
        # pipeline can checkpoint the incremental watermark after each batch.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )
