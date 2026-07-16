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
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kandji.settings import (
    EU_API_HOST_TEMPLATE,
    KANDJI_ENDPOINTS,
    US_API_HOST_TEMPLATE,
    KandjiEndpointConfig,
)

REGION_TEMPLATES = {
    "us": US_API_HOST_TEMPLATE,
    "eu": EU_API_HOST_TEMPLATE,
}


def build_base_url(subdomain: str, region: str) -> str:
    """Build the tenant- and region-scoped API base URL (with the `/api/v1` prefix).

    Raises `ValueError` for an unknown region or an empty/malformed subdomain — Kandji subdomains
    are a single DNS label, so anything with a dot or slash is rejected before it reaches the network.
    """
    template = REGION_TEMPLATES.get(region.lower().strip())
    if template is None:
        raise ValueError("Region must be either 'us' or 'eu'.")

    clean_subdomain = subdomain.strip()
    if not clean_subdomain or any(c in clean_subdomain for c in "./ "):
        raise ValueError("Subdomain must be the single label from your Kandji API URL (e.g. 'accuhive').")

    return template.format(subdomain=clean_subdomain)


def _auth_headers(api_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_token}", "Accept": "application/json"}


def _rest_api_client_config(base_url: str, api_token: str) -> ClientConfig:
    return {
        "base_url": base_url,
        "auth": {"type": "bearer", "token": api_token},
        "headers": {"Accept": "application/json"},
    }


def _list_paginator(config: KandjiEndpointConfig) -> OffsetPaginator:
    return OffsetPaginator(
        limit=config.page_size,
        offset_param="offset",
        limit_param="limit",
        total_path=config.total_path,
    )


def validate_credentials(
    api_token: str, subdomain: str, region: str, schema_name: Optional[str] = None
) -> tuple[bool, str | None]:
    """Probe the token against List Devices — the cheapest authenticated call.

    Accepts a 403 at source-create (a token may legitimately lack scope for some endpoints, which the
    user can still deselect); a 403 for a specific schema is surfaced as a permission error.
    """
    try:
        base_url = build_base_url(subdomain, region)
    except ValueError as exc:
        return False, str(exc)

    try:
        response = make_tracked_session().get(
            f"{base_url}/devices",
            headers=_auth_headers(api_token),
            params={"limit": 1},
            timeout=10,
        )
    except RequestException as exc:
        return False, f"Could not reach the Kandji API: {exc}"

    if response.status_code == 401:
        return False, "Invalid Kandji API token."
    if response.status_code == 403:
        if schema_name is not None:
            return False, "Your Kandji API token is missing the scope required for this table."
        # Valid token, missing scope for this endpoint — don't block source-create.
        return True, None
    if response.status_code != 200:
        return False, f"Kandji API returned an unexpected status ({response.status_code})."

    return True, None


def get_resource(config: KandjiEndpointConfig) -> EndpointResource:
    endpoint_config: Endpoint = {
        "path": config.path,
        "params": {},
        "data_selector": config.data_selector,
        "paginator": _list_paginator(config) if config.paginated else SinglePagePaginator(),
    }
    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def _make_source_response(config: KandjiEndpointConfig, items_fn) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items_fn,
        primary_keys=config.primary_key if isinstance(config.primary_key, list) else [config.primary_key],
        # Full refresh only — Kandji's list endpoints expose no stable updated-since cursor.
        sort_mode="asc",
    )


def kandji_source(
    api_token: str,
    subdomain: str,
    region: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    config = KANDJI_ENDPOINTS[endpoint]
    base_url = build_base_url(subdomain, region)
    client_config = _rest_api_client_config(base_url, api_token)

    if config.fanout is not None:
        parent_config = KANDJI_ENDPOINTS[config.fanout.parent_name]
        dependent_resource = cast(
            Iterable[Any],
            build_dependent_resource(
                endpoint_configs=KANDJI_ENDPOINTS,
                child_endpoint=endpoint,
                fanout=config.fanout,
                client_config=client_config,
                path_format_values={},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=None,
                should_use_incremental_field=False,
                page_size_param="limit",
                parent_endpoint_extra={
                    "paginator": _list_paginator(parent_config),
                    "data_selector": parent_config.data_selector,
                },
                child_endpoint_extra={
                    "paginator": SinglePagePaginator(),
                    "data_selector": config.data_selector,
                },
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
