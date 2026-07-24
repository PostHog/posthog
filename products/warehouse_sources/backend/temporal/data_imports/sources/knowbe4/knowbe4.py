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
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.knowbe4.settings import (
    KNOWBE4_ENDPOINTS,
    KNOWBE4_REGION_HOSTS,
    KnowBe4EndpointConfig,
)


def build_base_url(region: str) -> str:
    """Resolve the region-scoped Reporting API host. Raises `ValueError` for an unknown region."""
    host = KNOWBE4_REGION_HOSTS.get(region.lower().strip())
    if host is None:
        raise ValueError(f"Unknown KnowBe4 region {region!r}. Must be one of {sorted(KNOWBE4_REGION_HOSTS)}.")
    return host


def _client_config(base_url: str, api_key: str) -> ClientConfig:
    return {
        "base_url": base_url,
        "auth": {"type": "bearer", "token": api_key},
        "headers": {"Accept": "application/json"},
    }


def _list_paginator() -> PageNumberPaginator:
    # KnowBe4 pages start at 1 and terminate on an empty array — no total-count field is
    # documented, so we can't stop a page early via `total_path`.
    return PageNumberPaginator(base_page=1, page_param="page", stop_after_empty_page=True)


def get_resource(config: KnowBe4EndpointConfig) -> EndpointResource:
    endpoint_config: Endpoint = {
        "path": config.path,
        "params": {"per_page": config.page_size, **config.extra_params},
        "data_selector": config.data_selector,
        "paginator": _list_paginator(),
    }
    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def _make_source_response(config: KnowBe4EndpointConfig, items_fn: Any) -> SourceResponse:
    primary_keys = config.primary_key if isinstance(config.primary_key, list) else [config.primary_key]
    return SourceResponse(
        name=config.name,
        items=items_fn,
        primary_keys=primary_keys,
        # Full refresh only — KnowBe4 exposes no server-side updated-since cursor on any
        # list endpoint, so pages are requested and consumed in their stable ascending order.
        sort_mode="asc",
    )


def knowbe4_source(
    api_key: str,
    region: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    config = KNOWBE4_ENDPOINTS[endpoint]
    base_url = build_base_url(region)
    client_config = _client_config(base_url, api_key)

    if config.fanout is not None:
        dependent_resource = cast(
            Iterable[Any],
            build_dependent_resource(
                endpoint_configs=KNOWBE4_ENDPOINTS,
                child_endpoint=endpoint,
                fanout=config.fanout,
                client_config=client_config,
                path_format_values={},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=None,
                should_use_incremental_field=False,
                page_size_param="per_page",
                parent_endpoint_extra={
                    "paginator": _list_paginator(),
                    "data_selector": KNOWBE4_ENDPOINTS[config.fanout.parent_name].data_selector,
                },
                child_endpoint_extra={
                    "paginator": _list_paginator(),
                    "data_selector": config.data_selector,
                },
                child_params_extra=config.extra_params or None,
            ),
        )
        return _make_source_response(config, lambda: dependent_resource)

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {"write_disposition": "replace"},
        "resources": [get_resource(config)],
    }
    resource = rest_api_resource(rest_config, team_id, job_id, None)
    return _make_source_response(config, lambda: resource)


def validate_credentials(api_key: str, region: str, schema_name: str | None = None) -> tuple[bool, str | None]:
    """Probe the token against `/v1/account` — the cheapest authenticated call, and one every
    KnowBe4 Reporting API token can reach regardless of subscription tier."""
    try:
        base_url = build_base_url(region)
    except ValueError as exc:
        return False, str(exc)

    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            f"{base_url}/v1/account",
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=10,
        )
    except RequestException as exc:
        return False, f"Could not reach the KnowBe4 API: {exc}"

    if response.status_code == 401:
        return False, "Invalid KnowBe4 API key. Please check your key and try again."
    if response.status_code == 403:
        if schema_name is not None:
            return False, "Your KnowBe4 API key does not have permission to read this table."
        return True, None
    if response.status_code != 200:
        return False, f"KnowBe4 API returned an unexpected status ({response.status_code})."

    return True, None
