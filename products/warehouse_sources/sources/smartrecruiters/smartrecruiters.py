from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    ClientConfig,
    Endpoint,
    JSONResponseCursorPaginator,
    OffsetPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    build_dependent_resource,
    frozen,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)
from products.warehouse_sources.sources.smartrecruiters.settings import (
    BASE_URL,
    PAGE_SIZE,
    SMARTRECRUITERS_ENDPOINTS,
    SmartRecruitersEndpointConfig,
)

# A one-row job search is the cheapest call every API key can make.
PROBE_URL = f"{BASE_URL}/jobs?limit=1"


@frozen
class SmartRecruitersResumeConfig:
    # Top-level endpoints: the next page id (cursor endpoints) or the next offset (offset endpoints).
    page_id: str | None = None
    offset: int | None = None
    # Fan-out endpoints resume by parent job: the parents already synced, the one in progress, and
    # its paginator state. See `_make_paginate_dependent_resource` in the shared rest_source.
    completed: list[str] | None = None
    current: str | None = None
    child_state: dict[str, Any] | None = None


def format_updated_after(value: Any) -> str:
    """Format a watermark as the `yyyy-MM-ddTHH:mm:ss.SSSZ` UTC string that `updatedAfter` takes."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return str(value)


def _paginator(config: SmartRecruitersEndpointConfig) -> BasePaginator:
    if config.pagination == "offset":
        return OffsetPaginator(limit=PAGE_SIZE, total_path="totalFound")
    if config.pagination == "single":
        return SinglePagePaginator()
    return JSONResponseCursorPaginator(cursor_path=config.cursor_path, cursor_param=config.cursor_param)


def _client_config(api_key: str, paginator: BasePaginator) -> ClientConfig:
    return {
        "base_url": BASE_URL,
        "headers": {"Accept": "application/json"},
        "auth": {"type": "api_key", "name": "X-SmartToken", "api_key": api_key, "location": "header"},
        "paginator": paginator,
    }


def _build_params(
    config: SmartRecruitersEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = dict(config.params)
    if config.page_size_param is not None:
        params[config.page_size_param] = config.page_size
    if config.incremental_fields and should_use_incremental_field and db_incremental_field_last_value:
        params["updatedAfter"] = format_updated_after(db_incremental_field_last_value)
    return params


def _make_source_response(
    config: SmartRecruitersEndpointConfig, items: Any, column_hints: Any = None
) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=column_hints,
    )


def _top_level_source(
    config: SmartRecruitersEndpointConfig,
    api_key: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SmartRecruitersResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key, _paginator(config)),
        "resource_defaults": {},
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path,
                    "params": _build_params(config, should_use_incremental_field, db_incremental_field_last_value),
                    "data_selector": "content",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.page_id:
            initial_paginator_state = {"cursor": resume.page_id}
        elif resume is not None and resume.offset is not None:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # The framework calls this only while a next page remains.
        if not state:
            return
        if state.get("cursor"):
            resumable_source_manager.save_state(SmartRecruitersResumeConfig(page_id=str(state["cursor"])))
        elif state.get("offset") is not None:
            resumable_source_manager.save_state(SmartRecruitersResumeConfig(offset=int(state["offset"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return _make_source_response(config, lambda: resource, column_hints=resource.column_hints)


def _fanout_source(
    config: SmartRecruitersEndpointConfig,
    api_key: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SmartRecruitersResumeConfig],
) -> SourceResponse:
    assert config.fanout is not None
    parent_config = SMARTRECRUITERS_ENDPOINTS[config.fanout.parent_name]

    initial_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and (resume.completed or resume.current):
            initial_state = {
                "completed": resume.completed or [],
                "current": resume.current,
                "child_state": resume.child_state,
            }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(
                SmartRecruitersResumeConfig(
                    completed=state.get("completed"),
                    current=state.get("current"),
                    child_state=state.get("child_state"),
                )
            )

    parent_endpoint_extra: Endpoint = {"data_selector": "content"}
    child_endpoint_extra: Endpoint = {"data_selector": "content", "paginator": _paginator(config)}

    dependent_resource = cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=SMARTRECRUITERS_ENDPOINTS,
            child_endpoint=config.name,
            fanout=config.fanout,
            client_config=_client_config(api_key, _paginator(parent_config)),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            parent_endpoint_extra=parent_endpoint_extra,
            child_endpoint_extra=child_endpoint_extra,
            # The parent page size rides in `fanout.parent_params`; the child endpoints take none.
            page_size_param=None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        ),
    )
    return _make_source_response(config, lambda: dependent_resource)


def smartrecruiters_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SmartRecruitersResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SMARTRECRUITERS_ENDPOINTS[endpoint]

    if config.fanout is not None:
        return _fanout_source(config, api_key, team_id, job_id, resumable_source_manager)

    return _top_level_source(
        config,
        api_key,
        team_id,
        job_id,
        resumable_source_manager,
        should_use_incremental_field,
        db_incremental_field_last_value,
    )


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    """Probe a one-row job search. Returns `(ok, status_code)`, with `None` on a transport error."""
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        PROBE_URL,
        headers={"X-SmartToken": api_key, "Accept": "application/json"},
        # The key rides in a custom header, which `requests` does not strip on a redirect.
        allow_redirects=False,
    )
