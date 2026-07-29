from collections.abc import Callable, Iterable
from typing import Any, cast

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
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartengage.settings import (
    SMARTENGAGE_BASE_URL,
    SMARTENGAGE_ENDPOINTS,
    SmartEngageEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 30


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": SMARTENGAGE_BASE_URL,
        "auth": {"type": "bearer", "token": api_key},
        "headers": {"Accept": "application/json"},
    }


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    try:
        response = make_tracked_session().get(
            f"{SMARTENGAGE_BASE_URL}/avatars/list",
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except RequestException as exc:
        return False, f"SmartEngage request failed: {exc}"

    if response.status_code in (401, 403):
        return False, "Invalid SmartEngage API key"
    if response.status_code != 200:
        return False, f"SmartEngage API returned status {response.status_code}"

    # List endpoints return a bare JSON array; anything else (e.g. an error object served
    # with a 200) means the key is not usable.
    try:
        payload = response.json()
    except ValueError:
        return False, "SmartEngage API returned an unexpected response"
    if not isinstance(payload, list):
        return False, "SmartEngage API returned an unexpected response"

    return True, None


def get_resource(endpoint: str) -> EndpointResource:
    config = SMARTENGAGE_ENDPOINTS[endpoint]
    if config.fanout:
        raise ValueError(f"Fan-out endpoint '{endpoint}' must use the fan-out path")

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": {},
        # List endpoints return a bare JSON array with no pagination.
        "data_selector": "$",
        "paginator": SinglePagePaginator(),
    }

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def _make_source_response(
    endpoint_config: SmartEngageEndpointConfig, items_fn: Callable[[], Iterable[Any]]
) -> SourceResponse:
    # No SmartEngage table exposes a stable timestamp, so there is no partitioning.
    return SourceResponse(
        name=endpoint_config.name,
        items=items_fn,
        primary_keys=endpoint_config.primary_key,
    )


def smartengage_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    endpoint_config = SMARTENGAGE_ENDPOINTS[endpoint]

    if endpoint_config.fanout:
        dependent_resource = cast(
            Iterable[Any],
            build_dependent_resource(
                endpoint_configs=SMARTENGAGE_ENDPOINTS,
                child_endpoint=endpoint,
                fanout=endpoint_config.fanout,
                client_config=_client_config(api_key),
                path_format_values={},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=None,
                # SmartEngage list endpoints take no page-size param — they return the
                # full collection in one response.
                page_size_param=None,
                parent_endpoint_extra={"paginator": SinglePagePaginator(), "data_selector": "$"},
                child_endpoint_extra={"paginator": SinglePagePaginator(), "data_selector": "$"},
            ),
        )
        return _make_source_response(endpoint_config, lambda: dependent_resource)

    config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {"write_disposition": "replace"},
        "resources": [get_resource(endpoint=endpoint)],
    }

    resource = rest_api_resource(config, team_id, job_id, None)
    return _make_source_response(endpoint_config, lambda: resource)
