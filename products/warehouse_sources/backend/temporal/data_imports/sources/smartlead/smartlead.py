from collections.abc import Iterable
from typing import Any, Optional, cast
from urllib.parse import urlencode

from posthog.dataclasses import frozen

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
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.smartlead.settings import (
    BASE_URL,
    SMARTLEAD_ENDPOINTS,
    SmartleadEndpointConfig,
)


@frozen
class SmartleadResumeConfig:
    # Top-level offset-paginated endpoints resume from the next offset. None means "start over".
    next_offset: int | None = None
    # Fan-out endpoints resume by parent: the campaign paths already fully synced, the campaign
    # in progress, and that campaign's paginator state — see
    # `common.rest_source.__init__._make_paginate_dependent_resource`.
    completed: list[str] | None = None
    current: str | None = None
    child_state: dict[str, Any] | None = None


def _paginator(config: SmartleadEndpointConfig) -> BasePaginator:
    if config.pagination == "offset":
        # Smartlead reports totals as strings (e.g. `total_leads: "150"`), which the numeric
        # total check ignores, so the short-page fallback is what terminates pagination.
        return OffsetPaginator(limit=config.page_size, total_path=None)
    return SinglePagePaginator()


def _client_config(api_key: str, paginator: BasePaginator) -> ClientConfig:
    return {
        "base_url": BASE_URL,
        "headers": {"Accept": "application/json"},
        # Smartlead's only auth method is the `api_key` query param. The framework auth config
        # redacts the key from logged URLs and captured samples.
        "auth": {"type": "api_key", "name": "api_key", "api_key": api_key, "location": "query"},
        "paginator": paginator,
    }


def _endpoint_extra(config: SmartleadEndpointConfig) -> Endpoint:
    extra: Endpoint = {"paginator": _paginator(config)}
    if config.data_selector:
        extra["data_selector"] = config.data_selector
    if config.expects_list:
        # Fail loud on a response shape change instead of silently syncing 0 rows.
        extra["data_selector_required"] = True
    return extra


def _redact_fields_mapper(fields: tuple[str, ...]):
    def _mapper(row: dict[str, Any]) -> dict[str, Any]:
        for field_name in fields:
            row.pop(field_name, None)
        return row

    return _mapper


def _make_source_response(config: SmartleadEndpointConfig, items: Any, column_hints: Any = None) -> SourceResponse:
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
    config: SmartleadEndpointConfig,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SmartleadResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    endpoint_config: Endpoint = {"path": config.path, "params": {}}
    endpoint_config.update(_endpoint_extra(config))

    resource: dict[str, Any] = {
        "name": endpoint,
        "endpoint": endpoint_config,
    }
    if config.redact_fields:
        resource["data_map"] = _redact_fields_mapper(config.redact_fields)

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key, _paginator(config)),
        "resource_defaults": {},
        "resources": [cast(Any, resource)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.pagination == "offset" and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_offset:
            initial_paginator_state = {"offset": resume.next_offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while more pages remain; save AFTER a page is yielded so a crash re-yields
        # the last page rather than skipping it. Single-page endpoints never produce state.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(SmartleadResumeConfig(next_offset=int(state["offset"])))

    built = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return _make_source_response(config, lambda: built, column_hints=built.column_hints)


def _fanout_source(
    config: SmartleadEndpointConfig,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SmartleadResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    incremental_field: str | None,
) -> SourceResponse:
    assert config.fanout is not None
    parent_config = SMARTLEAD_ENDPOINTS[config.fanout.parent_name]

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
                SmartleadResumeConfig(
                    completed=state.get("completed"),
                    current=state.get("current"),
                    child_state=state.get("child_state"),
                )
            )

    dependent_resource = cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=SMARTLEAD_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=config.fanout,
            client_config=_client_config(api_key, _paginator(config)),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
            incremental_field=incremental_field,
            # The campaign parent list is unpaginated while children page with offset/limit, so
            # each side carries its own paginator instead of sharing the client's.
            parent_endpoint_extra=_endpoint_extra(parent_config),
            child_endpoint_extra=_endpoint_extra(config),
            # The parent takes no page-size param (unpaginated); the children's OffsetPaginator
            # injects `offset` and `limit` itself.
            page_size_param=None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        ),
    )

    return _make_source_response(config, lambda: dependent_resource)


def smartlead_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SmartleadResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = SMARTLEAD_ENDPOINTS[endpoint]

    if config.fanout is not None:
        return _fanout_source(
            config,
            api_key,
            endpoint,
            team_id,
            job_id,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
            incremental_field,
        )

    return _top_level_source(
        config,
        api_key,
        endpoint,
        team_id,
        job_id,
        resumable_source_manager,
        db_incremental_field_last_value,
    )


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    """Probe the email accounts list with limit=1 to confirm the API key is genuine.

    Returns ``(ok, status_code)``. ``status_code`` is ``None`` on a transport error.
    """
    query = urlencode({"api_key": api_key, "offset": 0, "limit": 1})
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{BASE_URL}/email-accounts/?{query}",
        headers={"Accept": "application/json"},
        # The key rides in the query string; following a redirect would replay it to the
        # redirect target.
        allow_redirects=False,
    )
