import dataclasses
from typing import Any, Optional, cast

from requests import Response

from products.warehouse_sources.sources.circle_so.settings import (
    BASE_URL,
    CIRCLE_SO_ENDPOINTS,
    PER_PAGE,
    CircleSoEndpointConfig,
)
from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    Endpoint,
    PageNumberPaginator,
    Resource,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    build_dependent_resource,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)

# Cheap single-object call that every Admin API v2 token can read.
PROBE_PATH = "/community"

_RECORDS: Endpoint = {"data_selector": "records", "data_selector_required": True}


@dataclasses.dataclass(frozen=False)
class CircleSoResumeConfig:
    # Next 1-indexed page of a top-level list.
    next_page: Optional[int] = None
    # `build_dependent_resource` checkpoint for a fan-out table.
    fanout_state: Optional[dict[str, Any]] = None


class CircleSoPaginator(PageNumberPaginator):
    """Page-number pagination that stops on `has_next_page: false`.

    Every request counts toward the plan's monthly quota, so the walk ends on the flag instead of
    paying for an extra empty page. An empty page still ends it if the flag is missing.
    """

    def __init__(self) -> None:
        super().__init__(base_page=1, page_param="page")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if not self._has_next_page:
            return
        try:
            body = response.json()
        except Exception:
            return
        if isinstance(body, dict) and body.get("has_next_page") is False:
            self._has_next_page = False


def _client_config(api_token: str) -> ClientConfig:
    return {
        "base_url": BASE_URL,
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_token},
        "paginator": CircleSoPaginator(),
    }


def _list_resource(
    api_token: str,
    config: CircleSoEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CircleSoResumeConfig],
) -> Resource:
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_token),
        "resource_defaults": {},
        "resources": [
            {
                "name": config.name,
                "table_name": config.name,
                "write_disposition": "replace",
                "endpoint": {
                    "path": config.path,
                    "params": {"per_page": PER_PAGE, **config.params},
                    **_RECORDS,
                },
                "table_format": "delta",
            }
        ],
    }

    current_page = 1
    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_page:
            current_page = resume.next_page
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        nonlocal current_page
        # The paginator reports no state for the last page. Point past it, so a resumed attempt
        # reads one empty page instead of loading the last page a second time.
        next_page = int(state["page"]) if state and state.get("page") is not None else current_page + 1
        resumable_source_manager.save_state(CircleSoResumeConfig(next_page=next_page))
        current_page = next_page

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _fanout_resource(
    api_token: str,
    config: CircleSoEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CircleSoResumeConfig],
) -> Resource:
    assert config.fanout is not None
    parent = CIRCLE_SO_ENDPOINTS[config.fanout.parent_name]
    fanout = dataclasses.replace(config.fanout, parent_params=dict(parent.params))

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        resumable_source_manager.save_state(CircleSoResumeConfig(fanout_state=state))

    return cast(
        Resource,
        build_dependent_resource(
            endpoint_configs=CIRCLE_SO_ENDPOINTS,
            child_endpoint=config.name,
            fanout=fanout,
            client_config=_client_config(api_token),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            parent_endpoint_extra=_RECORDS,
            # A child path that ends in its `{placeholder}` gets a single-page paginator by
            # default, which would drop every page after the first.
            child_endpoint_extra={**_RECORDS, "paginator": CircleSoPaginator()},
            child_params_extra=dict(config.params),
            page_size_param="per_page",
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
            resume_parent_pagination=True,
        ),
    )


def circle_so_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CircleSoResumeConfig],
) -> SourceResponse:
    config = CIRCLE_SO_ENDPOINTS[endpoint]

    if config.fanout is not None:
        resource = _fanout_resource(api_token, config, team_id, job_id, resumable_source_manager)
    else:
        resource = _list_resource(api_token, config, team_id, job_id, resumable_source_manager)

    partition_key = config.partition_key
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        column_hints=resource.column_hints,
        partition_count=1 if partition_key else None,
        partition_size=1 if partition_key else None,
        partition_mode="datetime" if partition_key else None,
        partition_format="month" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
    )


def check_access(api_token: str) -> Optional[int]:
    """Probe the community endpoint. Returns the HTTP status, or None when Circle is unreachable."""
    _, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{BASE_URL}{PROBE_PATH}",
        headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
    )
    return status
