import dataclasses
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.sources.holded.settings import HOLDED_API_HOST, HOLDED_ENDPOINTS
from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    EndpointResource,
    JSONResponseCursorPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)


@dataclasses.dataclass(frozen=True)
class HoldedResumeConfig:
    cursor: str


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
        "endpoint": {
            "path": config.path,
            "params": params,
            "paginator": paginator,
            # Every list response wraps its rows in `items`. A 200 without it means the shape
            # changed, so fail the sync instead of loading an empty table.
            "data_selector": "items",
            "data_selector_required": True,
        },
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

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url(api_version),
            "auth": {"type": "bearer", "token": api_key},
            "headers": {"Accept": "application/json"},
        },
        "resources": [get_resource(endpoint)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"cursor": resume_config.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("cursor"):
            resumable_source_manager.save_state(HoldedResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=resource.name,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
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
