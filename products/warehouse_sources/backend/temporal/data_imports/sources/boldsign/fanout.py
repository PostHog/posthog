from collections.abc import Iterable
from typing import Any, cast

from products.warehouse_sources.backend.temporal.data_imports.sources.boldsign.settings import BOLDSIGN_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse


def _client_config(base_url: str, api_key: str) -> ClientConfig:
    return {
        "base_url": base_url,
        # The API key rides the framework auth config so its value is redacted from logs; only
        # the non-secret Accept header is set here.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "api_key", "api_key": api_key, "name": "X-API-KEY", "location": "header"},
        "paginator": SinglePagePaginator(),
    }


def boldsign_fanout_source(
    base_url: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    """Build an endpoint that BoldSign only exposes per parent row, e.g. custom fields per brand."""
    config = BOLDSIGN_ENDPOINTS[endpoint]
    fanout = config.fanout
    if fanout is None:
        raise ValueError(f"BoldSign endpoint {endpoint} has no fan-out configured")
    parent_config = BOLDSIGN_ENDPOINTS[fanout.parent_name]

    # Neither side of this fan-out paginates, and the shared fan-out helper has no resume support:
    # the brand list is small and the children are replaced wholesale each run.
    resource = cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=BOLDSIGN_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=fanout,
            client_config=_client_config(base_url, api_key),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            # Neither endpoint takes a page-size param.
            page_size_param=None,
            parent_endpoint_extra={
                "data_selector": parent_config.data_key,
                "paginator": SinglePagePaginator(),
            },
            child_endpoint_extra={
                "data_selector": config.data_key,
                "paginator": SinglePagePaginator(),
            },
        ),
    )
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_mode=None,
    )
