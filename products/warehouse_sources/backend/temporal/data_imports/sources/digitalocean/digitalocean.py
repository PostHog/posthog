from collections.abc import Callable
from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    ClientConfig,
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


def _strip_sensitive_fields(sensitive_fields: frozenset[str]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    # Drop credential-bearing keys from each record before it's stored. Recurses through nested
    # dicts and lists because some secrets live inside spec/deployment objects, not at the top
    # level. Runs as a resource map, so it's the last thing to touch a record before persistence.
    def _scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: _scrub(item) for key, item in value.items() if key not in sensitive_fields}
        if isinstance(value, list):
            return [_scrub(item) for item in value]
        return value

    def _strip(record: dict[str, Any]) -> dict[str, Any]:
        return _scrub(record)

    return _strip


def digitalocean_source(api_key: str, endpoint: str, team_id: int, job_id: str) -> Resource:
    endpoint_config = DIGITALOCEAN_ENDPOINTS[endpoint]

    client_config: ClientConfig = {
        "base_url": DIGITALOCEAN_BASE_URL,
        "auth": {
            "type": "bearer",
            "token": api_key,
        },
        "paginator": _paginator(),
    }
    # Endpoints that return secrets (e.g. `databases`) must not have their raw responses
    # captured into HTTP samples, which happens before resource maps run. Opt them out of
    # sample capture while keeping the request metered, logged, and token-redacted.
    if endpoint_config.sensitive_fields:
        client_config["session"] = make_tracked_session(redact_values=(api_key,), capture=False)

    config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {
            "write_disposition": "replace",
        },
        "resources": [get_resource(endpoint_config)],
    }

    # No incremental support, so `db_incremental_field_last_value` is always None.
    resource = rest_api_resource(config, team_id, job_id, None)
    if endpoint_config.sensitive_fields:
        resource.add_map(_strip_sensitive_fields(endpoint_config.sensitive_fields))
    return resource


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
