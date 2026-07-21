import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.scale_ai.settings import (
    INCREMENTAL_PARAM_BY_FIELD,
    SCALE_AI_ENDPOINTS,
    ScaleAIEndpointConfig,
)

SCALE_AI_BASE_URL = "https://api.scale.com/v1"


@dataclasses.dataclass
class ScaleAIResumeConfig:
    # Cursor token for the `tasks` endpoint — the token the resumed run sends on its first request.
    # None means "start from the first page".
    next_token: str | None = None
    # Offset for the `batches` endpoint — the offset the resumed run sends on its first request.
    offset: int | None = None


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor as an ISO 8601 string, which Scale's time filters expect."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _build_params(
    config: ScaleAIEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if config.pagination in ("cursor", "offset"):
        params["limit"] = config.page_size

    if should_use_incremental_field and db_incremental_field_last_value:
        chosen = incremental_field or config.default_incremental_field
        param_name = INCREMENTAL_PARAM_BY_FIELD.get(chosen) if chosen else None
        if param_name:
            params[param_name] = _format_incremental_value(db_incremental_field_last_value)

    return params


def _paginator(config: ScaleAIEndpointConfig) -> BasePaginator:
    if config.pagination == "cursor":
        # `tasks` carries a `next_token` in the body; pagination stops when it's null.
        return JSONResponseCursorPaginator(cursor_path="next_token", cursor_param="next_token")
    if config.pagination == "offset":
        # `batches` uses limit/offset; a short or empty page ends pagination (OffsetPaginator default).
        return OffsetPaginator(
            limit=config.page_size,
            offset_param="offset",
            limit_param="limit",
            total_path=None,
        )
    # `projects` returns a single, non-paginated list.
    return SinglePagePaginator()


def validate_credentials(api_key: str) -> bool:
    """One cheap probe against the tasks list endpoint to confirm the API key is genuine."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{SCALE_AI_BASE_URL}/tasks?limit=1",
        auth=HTTPBasicAuth(api_key, ""),
    )
    return ok


def scale_ai_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ScaleAIResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = SCALE_AI_ENDPOINTS[endpoint]

    params = _build_params(config, should_use_incremental_field, db_incremental_field_last_value, incremental_field)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": SCALE_AI_BASE_URL,
            # Scale uses HTTP Basic auth with the API key as the username and an empty password.
            # The framework auth redacts the key from logs and raised error messages.
            "auth": {"type": "http_basic", "username": api_key, "password": ""},
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": config.data_selector,
                    "paginator": _paginator(config),
                },
            }
        ],
    }

    # Seed resume state and checkpoint back into the EXISTING ResumeConfig dataclass so old saved
    # state still parses. Only the paginated endpoints resume; projects is a single fetch.
    initial_paginator_state: Optional[dict[str, Any]] = None
    save_checkpoint = None

    if config.pagination == "cursor":
        if resumable_source_manager.can_resume():
            resume = resumable_source_manager.load_state()
            if resume is not None and resume.next_token is not None:
                initial_paginator_state = {"cursor": resume.next_token}

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            # Persist only when a next page remains; save AFTER a page is yielded so a crash
            # re-fetches the saved page (merge dedupes on the primary key) rather than losing it.
            if state and state.get("cursor") is not None:
                resumable_source_manager.save_state(ScaleAIResumeConfig(next_token=str(state["cursor"])))

    elif config.pagination == "offset":
        if resumable_source_manager.can_resume():
            resume = resumable_source_manager.load_state()
            if resume is not None and resume.offset is not None:
                initial_paginator_state = {"offset": resume.offset}

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state and state.get("offset") is not None:
                resumable_source_manager.save_state(ScaleAIResumeConfig(offset=int(state["offset"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        # Incremental filtering is done server-side via a static filter param in `params`, so the
        # framework's incremental descriptor is not used and no cursor value flows through here.
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # Scale returns every list endpoint newest-first by created_at and exposes no sort control,
        # so rows always arrive descending. "desc" persists the incremental watermark only at
        # successful job end, which is correct here: tasks filter on updated_at but arrive in
        # created_at order, so a per-batch (asc) watermark could advance past unread rows.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )
