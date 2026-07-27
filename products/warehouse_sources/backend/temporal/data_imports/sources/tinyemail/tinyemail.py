from collections.abc import Iterable
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
    BasePaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tinyemail.settings import (
    TINYEMAIL_BASE_URL,
    TINYEMAIL_ENDPOINTS,
    TinyemailEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 30

INVALID_CREDENTIALS_MESSAGE = (
    "Invalid tinyEmail API key. Generate a new key in tinyEmail under My account > API keys and reconnect. "
    "Note that tinyEmail API access requires an Enterprise plan."
)


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": TINYEMAIL_BASE_URL,
        "auth": {"type": "api_key", "name": "X-API-KEY", "api_key": api_key, "location": "header"},
        "headers": {"Accept": "application/json"},
        # The API responds directly on a fixed host, and `requests` would replay the
        # X-API-KEY header across a cross-host redirect — so never follow one.
        "allow_redirects": False,
    }


def _paginator(config: TinyemailEndpointConfig) -> BasePaginator:
    if not config.paginated:
        return SinglePagePaginator()
    return PageNumberPaginator(base_page=config.base_page, page_param="page")


def get_resource(endpoint: str) -> EndpointResource:
    config = TINYEMAIL_ENDPOINTS[endpoint]
    if config.fanout:
        raise ValueError(f"Fan-out endpoint '{endpoint}' must use the fan-out path")

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": {"size": config.page_size} if config.paginated else {},
        "data_selector": config.data_selector,
        "paginator": _paginator(config),
    }

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def _make_source_response(endpoint_config: TinyemailEndpointConfig, items_fn: Any) -> SourceResponse:
    return SourceResponse(
        name=endpoint_config.name,
        items=items_fn,
        primary_keys=endpoint_config.primary_key
        if isinstance(endpoint_config.primary_key, list)
        else [endpoint_config.primary_key],
    )


def tinyemail_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    endpoint_config = TINYEMAIL_ENDPOINTS[endpoint]

    if endpoint_config.fanout:
        parent_config = TINYEMAIL_ENDPOINTS[endpoint_config.fanout.parent_name]
        dependent_resource = cast(
            Iterable[Any],
            build_dependent_resource(
                endpoint_configs=TINYEMAIL_ENDPOINTS,
                child_endpoint=endpoint,
                fanout=endpoint_config.fanout,
                client_config=_client_config(api_key),
                path_format_values={},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=None,
                page_size_param="size",
                parent_endpoint_extra={
                    "paginator": _paginator(parent_config),
                    "data_selector": parent_config.data_selector,
                },
                child_endpoint_extra={
                    "paginator": _paginator(endpoint_config),
                    "data_selector": endpoint_config.data_selector,
                },
            ),
        )
        return _make_source_response(endpoint_config, lambda: dependent_resource)

    config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {"write_disposition": "replace"},
        "resources": [get_resource(endpoint)],
    }

    resource = rest_api_resource(config, team_id, job_id, None)
    return _make_source_response(endpoint_config, lambda: resource)


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)
    try:
        response = session.get(
            f"{TINYEMAIL_BASE_URL}/contacts",
            headers={"X-API-KEY": api_key, "Accept": "application/json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except RequestException as exc:
        return False, f"Could not connect to the tinyEmail API: {exc}"

    if response.status_code == 200:
        return True, None
    # tinyEmail has no per-endpoint scopes, so both 401 and 403 mean the key itself is unusable.
    if response.status_code in (401, 403):
        return False, INVALID_CREDENTIALS_MESSAGE
    return False, f"tinyEmail API returned an unexpected status code {response.status_code}"
