from collections.abc import Callable, Iterable
from typing import Any, cast

from requests.exceptions import RequestException

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
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.strato.settings import (
    STRATO_BASE_URL,
    STRATO_ENDPOINTS,
    StratoEndpointConfig,
)


def _client_config(api_token: str) -> ClientConfig:
    return {
        "base_url": STRATO_BASE_URL,
        "auth": {"type": "api_key", "name": "X-TOKEN", "api_key": api_token, "location": "header"},
        "headers": {"Accept": "application/json"},
        # Every list endpoint returns the whole collection in one response (see settings.py).
        "paginator": SinglePagePaginator(),
        # `requests` only strips its built-in `Authorization` header on a cross-origin redirect, so
        # the nonstandard `X-TOKEN` header would ride along to whatever host a 3xx points at. Refuse
        # to follow redirects so the token never leaves scp-api.strato.de.
        "allow_redirects": False,
    }


def _scrub_server_row(row: dict[str, Any]) -> dict[str, Any]:
    # `first_password` is the server's initial root password. It must never land in the warehouse.
    row.pop("first_password", None)
    return row


def _scrub_user_row(row: dict[str, Any]) -> dict[str, Any]:
    # `api.key` is the account's API token, the same credential this source authenticates with.
    # It must never land in the warehouse.
    api = row.get("api")
    if isinstance(api, dict):
        api.pop("key", None)
    return row


_DATA_MAPS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "Servers": _scrub_server_row,
    "Users": _scrub_user_row,
}


def get_resource(endpoint: str) -> EndpointResource:
    """Builds a top-level (non-fan-out) resource. `Snapshots` fans out from `Servers` and is
    built via `build_dependent_resource` in `strato_source`."""
    config = STRATO_ENDPOINTS[endpoint]
    if config.fanout:
        raise ValueError(f"Fan-out endpoint '{endpoint}' must use the fan-out path")

    resource: EndpointResource = {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": {"path": config.path},
        "table_format": "delta",
    }
    data_map = _DATA_MAPS.get(endpoint)
    if data_map is not None:
        resource["data_map"] = data_map
    return resource


def _make_source_response(config: StratoEndpointConfig, items_fn: Callable[[], Iterable[Any]]) -> SourceResponse:
    primary_keys = config.primary_key if isinstance(config.primary_key, list) else [config.primary_key]
    return SourceResponse(
        name=config.name,
        items=items_fn,
        primary_keys=primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def strato_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    endpoint_config = STRATO_ENDPOINTS[endpoint]
    client_config = _client_config(api_token)

    if endpoint_config.fanout:
        dependent_resource = cast(
            Iterable[Any],
            build_dependent_resource(
                endpoint_configs=STRATO_ENDPOINTS,
                child_endpoint=endpoint,
                fanout=endpoint_config.fanout,
                client_config=client_config,
                path_format_values={},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=None,
                page_size_param=None,
            ),
        )
        return _make_source_response(endpoint_config, lambda: dependent_resource)

    config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [get_resource(endpoint)],
    }

    resource = rest_api_resource(config, team_id, job_id, None)
    return _make_source_response(endpoint_config, lambda: resource)


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    try:
        # /ping_auth answers ["PONG"] when the token is valid, without touching any resource scope.
        # `allow_redirects=False`: keep the `X-TOKEN` header from being replayed to a redirect
        # target off scp-api.strato.de. A 3xx then falls through to the error return below.
        response = make_tracked_session(redact_values=(api_token,), allow_redirects=False).get(
            f"{STRATO_BASE_URL}/ping_auth",
            headers={"X-TOKEN": api_token, "Accept": "application/json"},
            timeout=10,
        )
    except RequestException as exc:
        return False, str(exc)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid STRATO API token. Create a token in the STRATO CloudPanel under Management > Users."
    if response.status_code == 406:
        return (
            False,
            "Your STRATO API user only accepts requests from specific IP addresses. "
            "Remove the IP restriction for this API user in the STRATO CloudPanel and try again.",
        )

    try:
        detail = response.json().get("message", response.text)
    except Exception:
        detail = response.text
    return False, str(detail)
