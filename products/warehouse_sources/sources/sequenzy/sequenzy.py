from datetime import UTC, datetime
from typing import Any, Optional

from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    ClientConfig,
    EndpointResource,
    JSONResponseCursorPaginator,
    OffsetPaginator,
    PageNumberPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    build_dependent_resource,
    frozen,
    make_tracked_session,
    rest_api_resource,
)
from products.warehouse_sources.sources.sequenzy.settings import (
    ENDPOINTS_CONFIG,
    EVENTS_MAX_WINDOW,
    SEQUENZY_BASE_URL,
    SequenzyEndpointConfig,
)


@frozen
class SequenzyResumeConfig:
    """Snapshot of the framework paginator's resume state.

    For a top-level endpoint exactly one of `cursor`, `offset`, `page` is set, matching its
    pagination style. The names mirror the keys of the framework paginators'
    `get_resume_state` dicts so the two shapes convert without a mapping table. A fan-out
    endpoint sets `fanout_state` (the shared dependent-resource paginator's state) and
    `window_end`, the end of the event time range, so a resumed run reads the same range.
    """

    cursor: str | None = None
    offset: int | None = None
    page: int | None = None
    fanout_state: dict[str, Any] | None = None
    window_end: str | None = None


def _paginator_state(resume: SequenzyResumeConfig) -> Optional[dict[str, Any]]:
    state = {key: getattr(resume, key) for key in ("cursor", "offset", "page") if getattr(resume, key) is not None}
    return state or None


def _to_utc(value: datetime | str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _time_filter_params(
    config: SequenzyEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    now: datetime,
) -> dict[str, Any]:
    if not config.event_time_range:
        return {}

    # Every request of a run, resumed attempts included, shares one `end`. A relative
    # `period` would move with each request, so events for a parent read early could fall
    # behind the watermark that later parents advance.
    start = now - EVENTS_MAX_WINDOW
    if should_use_incremental_field and db_incremental_field_last_value:
        start = max(_to_utc(db_incremental_field_last_value), start)
    return {"start": _format_timestamp(start), "end": _format_timestamp(now)}


def _make_paginator(config: SequenzyEndpointConfig) -> BasePaginator:
    if config.pagination == "cursor":
        return JSONResponseCursorPaginator(cursor_path="pagination.nextCursor", cursor_param="cursor")
    if config.pagination == "offset":
        return OffsetPaginator(
            limit=config.page_size,
            offset_param="offset",
            limit_param="limit",
            total_path="pagination.total",
        )
    if config.pagination == "page":
        return PageNumberPaginator(base_page=1, page_param="page", total_path="pagination.totalPages")
    return SinglePagePaginator()


def _request_params(config: SequenzyEndpointConfig, time_filter_params: dict[str, Any] | None = None) -> dict[str, Any]:
    params: dict[str, Any] = dict(config.params)
    # The cursor and page-number paginators only inject their own pagination param, so
    # the page size rides along as a plain query param. The offset paginator sends
    # `limit` itself.
    if config.pagination in ("cursor", "page"):
        params["limit"] = config.page_size
    params.update(time_filter_params or {})
    return params


def get_resource(name: str, time_filter_params: dict[str, Any] | None = None) -> EndpointResource:
    config = ENDPOINTS_CONFIG[name]

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": {
            "path": config.path,
            "data_selector": config.data_selector,
            "params": _request_params(config, time_filter_params),
            "paginator": _make_paginator(config),
        },
        "table_format": "delta",
    }


def sequenzy_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SequenzyResumeConfig],
    company_id: str | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    endpoint_config = ENDPOINTS_CONFIG[endpoint]

    headers = {"Accept": "application/json"}
    if company_id:
        # Account API keys (seq_user_) span workspaces and need the target workspace
        # named per request; workspace keys (seq_live_) are already bound to one.
        headers["x-company-id"] = company_id

    client_config: ClientConfig = {
        "base_url": SEQUENZY_BASE_URL,
        "auth": {
            "type": "bearer",
            "token": api_key,
        },
        "headers": headers,
    }

    resume_config: SequenzyResumeConfig | None = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()

    now = datetime.now(UTC)
    if resume_config is not None and resume_config.window_end:
        now = _to_utc(resume_config.window_end)
    time_filter_params = _time_filter_params(
        endpoint_config, should_use_incremental_field, db_incremental_field_last_value, now
    )

    resource: Any
    if endpoint_config.fanout is not None:
        parent_config = ENDPOINTS_CONFIG[endpoint_config.fanout.parent_name]
        window_end = _format_timestamp(now)

        def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state:
                resumable_source_manager.save_state(SequenzyResumeConfig(fanout_state=state, window_end=window_end))

        resource = build_dependent_resource(
            endpoint_configs=ENDPOINTS_CONFIG,
            child_endpoint=endpoint,
            fanout=endpoint_config.fanout,
            client_config=client_config,
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            should_use_incremental_field=should_use_incremental_field,
            incremental_config_factory=lambda _field: None,
            page_size_param=None,
            parent_endpoint_extra={
                "paginator": _make_paginator(parent_config),
                "data_selector": parent_config.data_selector,
            },
            child_endpoint_extra={
                "paginator": _make_paginator(endpoint_config),
                "data_selector": endpoint_config.data_selector,
            },
            child_params_extra=_request_params(endpoint_config, time_filter_params),
            resume_hook=save_fanout_checkpoint,
            initial_paginator_state=resume_config.fanout_state if resume_config else None,
            resume_parent_pagination=True,
        )
    else:
        config: RESTAPIConfig = {
            "client": client_config,
            "resource_defaults": {
                "write_disposition": "replace",
            },
            "resources": [get_resource(endpoint, time_filter_params)],
        }

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if not state or not endpoint_config.resume_pages:
                return
            resumable_source_manager.save_state(
                SequenzyResumeConfig(
                    cursor=state.get("cursor"),
                    offset=state.get("offset"),
                    page=state.get("page"),
                )
            )

        resource = rest_api_resource(
            config,
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=(
                _paginator_state(resume_config) if resume_config and endpoint_config.resume_pages else None
            ),
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=list(endpoint_config.primary_keys),
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        sort_mode=endpoint_config.sort_mode,
    )


def validate_credentials(api_key: str, company_id: str | None = None) -> tuple[bool, str | None]:
    # A non-ASCII key cannot be encoded into the Authorization header (requests uses
    # latin-1), which would otherwise surface a raw UnicodeEncodeError to the user.
    if not api_key.isascii():
        return (
            False,
            "Your Sequenzy API key contains an unsupported character (for example an invisible one "
            "pasted from another app). Retype it by hand and try again.",
        )

    headers = {"Authorization": f"Bearer {api_key}"}
    if company_id:
        headers["x-company-id"] = company_id

    # Documented by Sequenzy as the credential-validation endpoint for integrations.
    res = make_tracked_session(redact_values=(api_key,)).get(
        f"{SEQUENZY_BASE_URL}/subscribers/me",
        headers=headers,
        timeout=10,
    )
    if res.status_code == 200:
        return True, None
    if res.status_code == 401:
        return False, "Invalid API key. Check the key in Sequenzy under Settings > API Keys and try again."
    if res.status_code == 403:
        return (
            False,
            "Sequenzy could not find that workspace. If you use an account API key (seq_user_), "
            "enter the company ID of the workspace to sync.",
        )
    return False, f"Sequenzy returned an unexpected response (HTTP {res.status_code}). Try again later."
