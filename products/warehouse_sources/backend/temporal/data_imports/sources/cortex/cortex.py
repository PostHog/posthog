from collections.abc import Iterable
from typing import Any, Optional, cast

from requests.exceptions import RequestException

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
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
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cortex.settings import (
    CORTEX_BASE_URL,
    CORTEX_ENDPOINTS,
    CortexEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 30


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": CORTEX_BASE_URL,
        "auth": {"type": "bearer", "token": api_key},
        "headers": {"Accept": "application/json"},
    }


def _list_paginator(config: CortexEndpointConfig) -> BasePaginator:
    if not config.paginated:
        return SinglePagePaginator()
    return PageNumberPaginator(page_param="page", total_path=config.total_path)


def validate_credentials(api_key: str, schema_name: Optional[str] = None) -> tuple[bool, str | None]:
    """Probe List Entities with `pageSize=1` — the cheapest authenticated call.

    Accepts a 403 at source-create (a key may legitimately lack scope for some resources, which
    the user can still deselect); a 403 for a specific schema is surfaced as a permission error.
    """
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            f"{CORTEX_BASE_URL}/catalog",
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            params={"page": 0, "pageSize": 1},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except RequestException as exc:
        return False, f"Could not reach the Cortex API: {exc}"

    if response.status_code == 401:
        return False, "Invalid Cortex API key."
    if response.status_code == 403:
        if schema_name is not None:
            return False, "Your Cortex API key is missing the scope required for this table."
        return True, None
    if response.status_code != 200:
        return False, f"Cortex API returned an unexpected status ({response.status_code})."

    return True, None


def _flatten_scorecard_score(item: dict[str, Any]) -> dict[str, Any]:
    """Pull the nested `service` identifiers to the row root so they can back the primary key."""
    service = item.get("service") or {}
    item["service_tag"] = service.get("tag")
    item["service_id"] = service.get("id")
    item["service_name"] = service.get("name")
    return item


def _flatten_relationship(item: dict[str, Any]) -> dict[str, Any]:
    """Pull the nested source/destination entity identifiers to the row root for the primary key."""
    source_entity = item.get("sourceEntity") or {}
    destination_entity = item.get("destinationEntity") or {}
    item["source_entity_tag"] = source_entity.get("tag")
    item["source_entity_id"] = source_entity.get("id")
    item["destination_entity_tag"] = destination_entity.get("tag")
    item["destination_entity_id"] = destination_entity.get("id")
    return item


_FANOUT_FLATTENERS = {
    "scorecard_scores": _flatten_scorecard_score,
    "relationships": _flatten_relationship,
}


def get_resource(config: CortexEndpointConfig) -> EndpointResource:
    endpoint_config: Endpoint = {
        "path": config.path,
        "params": {"pageSize": config.page_size} if config.paginated else {},
        "data_selector": config.data_selector,
        "paginator": _list_paginator(config),
    }
    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def _make_source_response(config: CortexEndpointConfig, items_fn: Any) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items_fn,
        primary_keys=config.primary_key,
        # Full refresh only — Cortex's list endpoints expose no stable updated-since cursor.
        sort_mode="asc",
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def cortex_source(api_key: str, endpoint: str, team_id: int, job_id: str) -> SourceResponse:
    config = CORTEX_ENDPOINTS[endpoint]
    client_config = _client_config(api_key)

    if config.fanout is not None:
        parent_config = CORTEX_ENDPOINTS[config.fanout.parent_name]
        resource = cast(
            Any,
            build_dependent_resource(
                endpoint_configs=CORTEX_ENDPOINTS,
                child_endpoint=endpoint,
                fanout=config.fanout,
                client_config=client_config,
                path_format_values={},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=None,
                should_use_incremental_field=False,
                page_size_param="pageSize",
                parent_endpoint_extra={
                    "paginator": _list_paginator(parent_config),
                    "data_selector": parent_config.data_selector,
                },
                child_endpoint_extra={
                    "paginator": _list_paginator(config),
                    "data_selector": config.data_selector,
                },
            ),
        )
        flatten_fn = _FANOUT_FLATTENERS.get(config.name)
        if flatten_fn is not None:
            resource = resource.add_map(flatten_fn)
        dependent_resource = cast(Iterable[Any], resource)
        return _make_source_response(config, lambda: dependent_resource)

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {"write_disposition": "replace"},
        "resources": [get_resource(config)],
    }
    resource_response = rest_api_resource(rest_config, team_id, job_id, None)
    return _make_source_response(config, lambda: resource_response)


__all__ = ["cortex_source", "get_resource", "validate_credentials"]
