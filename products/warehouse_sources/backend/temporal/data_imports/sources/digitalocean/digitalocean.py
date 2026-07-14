from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONLinkPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.settings import (
    DIGITALOCEAN_ENDPOINTS,
    PAGE_SIZE,
    DigitalOceanEndpointConfig,
)

DIGITALOCEAN_BASE_URL = "https://api.digitalocean.com"


def _paginator() -> JSONLinkPaginator:
    # DigitalOcean returns the next page as a full URL under `links.pages.next`; it's
    # absent on the final page, which terminates pagination.
    return JSONLinkPaginator(next_url_path="links.pages.next")


def get_resource(endpoint_config: DigitalOceanEndpointConfig) -> EndpointResource:
    params: dict[str, object] = {"per_page": PAGE_SIZE}
    params.update(endpoint_config.extra_params)

    return {
        "name": endpoint_config.name,
        "table_name": endpoint_config.name,
        # No server-side timestamp filter exists on any DigitalOcean list endpoint, so we
        # always replace the whole table rather than merge on an incremental cursor.
        "write_disposition": "replace",
        "endpoint": {
            "data_selector": endpoint_config.data_selector,
            "path": endpoint_config.path,
            "paginator": _paginator(),
            "params": params,
        },
        "table_format": "delta",
    }


def digitalocean_source(api_key: str, endpoint: str, team_id: int, job_id: str) -> Resource:
    endpoint_config = DIGITALOCEAN_ENDPOINTS[endpoint]

    config: RESTAPIConfig = {
        "client": {
            "base_url": DIGITALOCEAN_BASE_URL,
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
            "paginator": _paginator(),
        },
        "resource_defaults": {
            "write_disposition": "replace",
        },
        "resources": [get_resource(endpoint_config)],
    }

    # No incremental support, so `db_incremental_field_last_value` is always None.
    return rest_api_resource(config, team_id, job_id, None)


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    """Probe `/v2/account` to confirm the token is genuine.

    `/v2/account` is the cheapest authenticated probe and every token can read it, so it
    confirms the token without depending on any resource-specific scope. Returns
    ``(ok, status_code)``; ``status_code`` is ``None`` on a transport error. The caller
    distinguishes an auth rejection (401/403) from a transient failure so it never tells the
    user their token is invalid when DigitalOcean was merely rate-limited or unavailable.
    """
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            f"{DIGITALOCEAN_BASE_URL}/v2/account",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
    except Exception:
        return False, None
    return response.status_code == 200, response.status_code
