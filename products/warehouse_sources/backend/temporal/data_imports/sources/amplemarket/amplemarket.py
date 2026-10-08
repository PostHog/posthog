from collections.abc import Iterable
from typing import Any, Optional, cast

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.amplemarket.settings import (
    AMPLEMARKET_ENDPOINTS,
    BASE_URL,
    AmplemarketEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

# Amplemarket responses carry HAL-style links; the next page is a relative URL the paginator
# resolves against the response URL.
NEXT_URL_PATH = "_links.next.href"


@frozen
class AmplemarketResumeConfig:
    next_url: str


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": BASE_URL,
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_key},
    }


def validate_credentials(api_key: str) -> bool:
    # /account-info is the cheapest authenticated probe: one object, no pagination, no credit
    # consumption.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{BASE_URL}/account-info",
        headers={"Accept": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    return ok


def _source_response(config: AmplemarketEndpointConfig, items: Iterable[Any]) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=lambda: items,
        primary_keys=[config.primary_key],
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def _fanout_source(api_key: str, endpoint: str, team_id: int, job_id: str) -> SourceResponse:
    """Fan a per-user endpoint (tasks) out over the users list.

    The parent users list is small and re-fetched each sync, so the fan-out is not resumable;
    each user's task pages follow their own `_links.next.href` chain, which carries the
    `user_id` filter forward.
    """
    config = AMPLEMARKET_ENDPOINTS[endpoint]
    assert config.fanout is not None
    parent_config = AMPLEMARKET_ENDPOINTS[config.fanout.parent_name]

    dependent_resource = cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=AMPLEMARKET_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=config.fanout,
            client_config=_client_config(api_key),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            should_use_incremental_field=False,
            # Requests follow the server's default page size (see settings.py).
            page_size_param=None,
            parent_endpoint_extra={
                "paginator": JSONResponsePaginator(next_url_path=NEXT_URL_PATH),
                "data_selector": parent_config.data_key,
            },
            child_endpoint_extra={
                "paginator": JSONResponsePaginator(next_url_path=NEXT_URL_PATH),
                "data_selector": config.data_key,
            },
        ),
    )

    return _source_response(config, dependent_resource)


def amplemarket_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AmplemarketResumeConfig],
) -> SourceResponse:
    config = AMPLEMARKET_ENDPOINTS[endpoint]

    if config.fanout is not None:
        return _fanout_source(api_key, endpoint, team_id, job_id)

    rest_config: RESTAPIConfig = {
        "client": {
            **_client_config(api_key),
            "paginator": JSONResponsePaginator(next_url_path=NEXT_URL_PATH),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "data_selector": config.data_key,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; state is staged before the page it covers is
        # yielded, so a crash re-yields that page and the merge dedupes on the primary key.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(AmplemarketResumeConfig(next_url=str(state["next_url"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return _source_response(config, resource)
