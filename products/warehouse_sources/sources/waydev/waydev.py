from collections.abc import Callable
from typing import Any, Optional, cast

from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    PageNumberPaginator,
    Resource,
    RESTAPIConfig,
    ResumableSourceManager,
    SinglePagePaginator,
    build_dependent_resource,
    frozen,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)
from products.warehouse_sources.sources.waydev.settings import (
    FANOUT_ENDPOINTS,
    INCIDENTS_PAGE_SIZE,
    REPOSITORIES_PAGE_SIZE,
    TEAMS_PAGE_SIZE,
)

BASE_URL = "https://api.waydev.co/v2"


@frozen
class WaydevResumeConfig:
    next_page: Optional[int] = None
    # Fan-out progress (finished parents, the parent in flight and its page). Shape owned by the
    # shared fan-out helper.
    fanout_state: Optional[dict[str, Any]] = None


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": BASE_URL,
        # The public reference sends the raw token under Authorization with no scheme prefix.
        "auth": {
            "type": "api_key",
            "name": "Authorization",
            "api_key": api_key,
            "location": "header",
        },
    }


def get_resource(name: str) -> EndpointResource:
    resources: dict[str, EndpointResource] = {
        "Metrics": {
            "name": "Metrics",
            "table_name": "metrics",
            "write_disposition": "replace",
            "endpoint": {
                "path": "/metrics",
                # Response is a bare JSON array with no pagination documented.
                "paginator": SinglePagePaginator(),
            },
            "table_format": "delta",
        },
        "Incidents": {
            "name": "Incidents",
            "table_name": "incidents",
            "write_disposition": "replace",
            "endpoint": {
                "path": "/incidents",
                "params": {"limit": INCIDENTS_PAGE_SIZE},
                "data_selector": "data",
                "paginator": PageNumberPaginator(base_page=1, page_param="page", stop_after_empty_page=True),
            },
            "table_format": "delta",
        },
        "Repositories": {
            "name": "Repositories",
            "table_name": "repositories",
            "write_disposition": "replace",
            "endpoint": {
                "path": "/repositories",
                # `state=all` includes repositories that are not selected for processing, so
                # repository IDs on other tables still resolve.
                "params": {"state": "all", "limit": REPOSITORIES_PAGE_SIZE},
                "data_selector": "values",
                "paginator": PageNumberPaginator(base_page=1, page_param="page", stop_after_empty_page=True),
            },
            "table_format": "delta",
        },
        "Contributors": {
            "name": "Contributors",
            "table_name": "contributors",
            "write_disposition": "replace",
            "endpoint": {
                "path": "/contributors",
                # No pagination is documented; the response carries every contributor.
                "data_selector": "contributors",
                "paginator": SinglePagePaginator(),
            },
            "table_format": "delta",
        },
        "Teams": {
            "name": "Teams",
            "table_name": "teams",
            "write_disposition": "replace",
            "endpoint": {
                "path": "/teams",
                "params": {"limit": TEAMS_PAGE_SIZE},
                "data_selector": "data",
                "paginator": PageNumberPaginator(
                    base_page=1, page_param="page", total_path="last_page", stop_after_empty_page=True
                ),
            },
            "table_format": "delta",
        },
    }
    return resources[name]


def _count_values_pages() -> Endpoint:
    return {
        "data_selector": "values",
        "paginator": PageNumberPaginator(base_page=1, page_param="page", stop_after_empty_page=True),
    }


def _last_page_pages() -> Endpoint:
    return {
        "data_selector": "data",
        "paginator": PageNumberPaginator(
            base_page=1, page_param="page", total_path="last_page", stop_after_empty_page=True
        ),
    }


# Team members share the teams envelope; pulls and commits share the repositories one.
_PAGES_BY_PARENT: dict[str, Callable[[], Endpoint]] = {
    "Repositories": _count_values_pages,
    "Teams": _last_page_pages,
}


def _fanout_resource(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[WaydevResumeConfig],
) -> Resource:
    fanout = FANOUT_ENDPOINTS[endpoint].fanout
    assert fanout is not None

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None and resume_config.fanout_state:
            initial_paginator_state = resume_config.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        resumable_source_manager.save_state(WaydevResumeConfig(fanout_state=state))

    pages = _PAGES_BY_PARENT[fanout.parent_name]
    resource = build_dependent_resource(
        endpoint_configs=FANOUT_ENDPOINTS,
        child_endpoint=endpoint,
        fanout=fanout,
        client_config=_client_config(api_key),
        path_format_values={},
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=None,
        parent_endpoint_extra=pages(),
        child_endpoint_extra=pages(),
        page_size_param=None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
        resume_parent_pagination=True,
    )
    return cast(Resource, resource)


def waydev_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[WaydevResumeConfig],
) -> Resource:
    if endpoint in FANOUT_ENDPOINTS and FANOUT_ENDPOINTS[endpoint].fanout is not None:
        return _fanout_resource(api_key, endpoint, team_id, job_id, resumable_source_manager)

    config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [get_resource(endpoint)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None and resume_config.next_page is not None:
            initial_paginator_state = {"page": resume_config.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles
        # cleanup on completion.
        if state and state.get("page"):
            resumable_source_manager.save_state(WaydevResumeConfig(next_page=int(state["page"])))

    return rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    """Probe the metrics endpoint to confirm the token is genuine."""
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{BASE_URL}/metrics",
        headers={"Authorization": api_key},
    )
