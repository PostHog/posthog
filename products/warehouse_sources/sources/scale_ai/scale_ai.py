import dataclasses
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional, cast
from urllib.parse import quote

from requests.auth import HTTPBasicAuth

from products.warehouse_sources.sources.scale_ai.settings import (
    ENCODED_NAME_FIELD,
    INCREMENTAL_PARAM_BY_FIELD,
    SCALE_AI_ENDPOINTS,
    ScaleAIEndpointConfig,
)
from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    ClientConfig,
    JSONResponseCursorPaginator,
    OffsetPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    build_dependent_resource,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)

SCALE_AI_BASE_URL = "https://api.scale.com/v1"


@dataclasses.dataclass(frozen=True)
class ScaleAIResumeConfig:
    # Cursor token for the `tasks` endpoint — the token the resumed run sends on its first request.
    # None means "start from the first page".
    next_token: str | None = None
    # Offset for the `batches` endpoint — the offset the resumed run sends on its first request.
    offset: int | None = None
    # Opaque per-parent checkpoint of the fan-out endpoints (`audits`, `batch_statuses`).
    fanout_state: dict[str, Any] | None = None


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


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": SCALE_AI_BASE_URL,
        # Scale uses HTTP Basic auth with the API key as the username and an empty password.
        # The framework auth redacts the key from logs and raised error messages.
        "auth": {"type": "http_basic", "username": api_key, "password": ""},
    }


def _add_encoded_name(row: dict[str, Any]) -> dict[str, Any]:
    # `safe=""` also encodes `/`, which would otherwise split the name into extra path segments.
    return {**row, ENCODED_NAME_FIELD: quote(str(row["name"]), safe="")}


def _make_source_response(config: ScaleAIEndpointConfig, items: Any, column_hints: Any = None) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items,
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
        column_hints=column_hints,
    )


def _fanout_source(
    config: ScaleAIEndpointConfig,
    api_key: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ScaleAIResumeConfig],
) -> SourceResponse:
    assert config.fanout is not None
    parent_config = SCALE_AI_ENDPOINTS[config.fanout.parent_name]

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state:
            resumable_source_manager.save_state(ScaleAIResumeConfig(fanout_state=dict(state)))

    resource = cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=SCALE_AI_ENDPOINTS,
            child_endpoint=config.name,
            fanout=config.fanout,
            client_config=_client_config(api_key),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            # Neither child endpoint has a server-side time filter, so both are full refresh.
            db_incremental_field_last_value=None,
            parent_endpoint_extra={
                "paginator": _paginator(parent_config),
                "data_selector": parent_config.data_selector,
            },
            child_endpoint_extra={"paginator": _paginator(config), "data_selector": config.data_selector},
            parent_data_map=_add_encoded_name if config.fanout.resolve_field == ENCODED_NAME_FIELD else None,
            # The page size goes in `parent_params`: the child endpoints document no `limit`.
            page_size_param=None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
            resume_parent_pagination=True,
        ),
    )
    return _make_source_response(config, lambda: resource)


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
    if config.fanout is not None:
        return _fanout_source(config, api_key, team_id, job_id, resumable_source_manager)

    params = _build_params(config, should_use_incremental_field, db_incremental_field_last_value, incremental_field)

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
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

    return _make_source_response(config, lambda: resource, column_hints=resource.column_hints)
