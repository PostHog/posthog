import dataclasses
from collections.abc import Callable, Iterable
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.sources.holded.settings import HOLDED_API_HOST, HOLDED_ENDPOINTS
from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    ClientConfig,
    Endpoint,
    EndpointResource,
    JSONResponseCursorPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    build_dependent_resource,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)


@dataclasses.dataclass(frozen=True)
class HoldedResumeConfig:
    # Flat listings resume from the next page cursor.
    cursor: Optional[str] = None
    # A fan-out resumes from the state `build_dependent_resource` checkpoints: which parents
    # finished and where the current one stopped.
    fanout_state: Optional[dict[str, Any]] = None


# The fan-out helper needs an int page size, which `HoldedEndpointConfig` does not guarantee.
@dataclasses.dataclass(frozen=True)
class _FanoutEndpoint:
    name: str
    path: str
    page_size: int
    incremental_fields: list[Any] = dataclasses.field(default_factory=list)
    default_incremental_field: Optional[str] = None


def _fanout_endpoint(name: str) -> _FanoutEndpoint:
    config = HOLDED_ENDPOINTS[name]
    if config.page_size is None:
        raise ValueError(f"Holded fan-out endpoint {name} must be cursor paginated")
    return _FanoutEndpoint(name=name, path=config.path, page_size=config.page_size)


class HoldedCursorPaginator(JSONResponseCursorPaginator):
    """Follows `cursor`, and also stops when `has_more` is false.

    Holded sends a null cursor on the last page. The `has_more` check stops a walk that would
    otherwise ask for one more empty page, which costs a call from the account's monthly quota.
    """

    def __init__(self) -> None:
        super().__init__(cursor_path="cursor", cursor_param="cursor", raise_on_repeated_cursor=True)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if not self._has_next_page:
            return
        body = response.json()
        if isinstance(body, dict) and body.get("has_more") is False:
            self._has_next_page = False


def base_url(api_version: str) -> str:
    return f"{HOLDED_API_HOST}/api/{api_version}"


def _list_endpoint_extra(paginator: BasePaginator | None = None) -> Endpoint:
    return {
        "paginator": paginator or HoldedCursorPaginator(),
        # Every list response wraps its rows in `items`. A 200 without it means the shape
        # changed, so fail the sync instead of loading an empty table.
        "data_selector": "items",
        "data_selector_required": True,
    }


def get_resource(endpoint: str) -> EndpointResource:
    config = HOLDED_ENDPOINTS[endpoint]
    params: dict[str, Any] = dict(config.params)
    paginator: BasePaginator
    if config.page_size is None:
        paginator = SinglePagePaginator()
    else:
        params["limit"] = config.page_size
        paginator = HoldedCursorPaginator()

    return {
        "name": endpoint,
        "table_name": endpoint,
        "write_disposition": "replace",
        "table_format": "delta",
        "endpoint": {"path": config.path, "params": params, **_list_endpoint_extra(paginator)},
    }


def holded_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[HoldedResumeConfig],
) -> SourceResponse:
    if endpoint not in HOLDED_ENDPOINTS:
        raise ValueError(f"Unknown Holded endpoint: {endpoint}")
    config = HOLDED_ENDPOINTS[endpoint]

    client_config: ClientConfig = {
        "base_url": base_url(api_version),
        "auth": {"type": "bearer", "token": api_key},
        "headers": {"Accept": "application/json"},
    }

    resume_config: Optional[HoldedResumeConfig] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()

    if config.fanout is not None:

        def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state:
                resumable_source_manager.save_state(HoldedResumeConfig(fanout_state=state))

        child = build_dependent_resource(
            endpoint_configs={
                config.fanout.parent_name: _fanout_endpoint(config.fanout.parent_name),
                endpoint: _fanout_endpoint(endpoint),
            },
            child_endpoint=endpoint,
            fanout=config.fanout,
            client_config=client_config,
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            parent_endpoint_extra=_list_endpoint_extra(),
            child_endpoint_extra=_list_endpoint_extra(),
            resume_hook=save_fanout_checkpoint,
            initial_paginator_state=resume_config.fanout_state if resume_config else None,
        )
        return _source_response(endpoint, lambda: child)

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resources": [get_resource(endpoint)],
    }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("cursor"):
            resumable_source_manager.save_state(HoldedResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=({"cursor": resume_config.cursor} if resume_config and resume_config.cursor else None),
    )
    return _source_response(endpoint, lambda: resource, resource.column_hints)


def _source_response(
    endpoint: str, items: Callable[[], Iterable[Any]], column_hints: Optional[dict[str, Any]] = None
) -> SourceResponse:
    config = HOLDED_ENDPOINTS[endpoint]
    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=column_hints,
    )


def check_credentials(api_key: str, api_version: str) -> tuple[bool, Optional[int]]:
    """Reads the account information, the cheapest call that needs only a valid key.

    Holded answers 403 both for a key it does not know and for a key without the
    `account:info.read` permission, so the caller cannot accept a 403 as a valid key.
    """
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{base_url(api_version)}/account",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
