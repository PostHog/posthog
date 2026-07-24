from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.settings import (
    CLOUDFLARE_ENDPOINTS,
    CloudflareEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.jsonpath_utils import (
    find_values,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)

CLOUDFLARE_BASE_URL = "https://api.cloudflare.com/client/v4"
# Cloudflare list pages cap at 50 by default; most endpoints allow more.
PAGE_SIZE = 50
# A token can list zones (account-level Zone:Read) without holding DNS:Read on
# every one of them. Per-zone 403/404s mean "this zone is inaccessible/gone" —
# skip it and keep syncing the rest rather than failing the whole stream.
ZONE_SKIP_STATUS_CODES = (403, 404)


class CloudflarePaginator(PageNumberPaginator):
    """Cloudflare page-number pagination: stop via ``result_info.total_pages``,
    with a short-page fallback for responses that omit it."""

    def __init__(self) -> None:
        super().__init__(base_page=1, page_param="page", total_path="result_info.total_pages")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if not self._has_next_page or not data:
            return
        try:
            values = find_values(self.total_path, response.json())
        except Exception:
            values = []
        total_pages = values[0] if values else None
        # Without a total-pages hint, a short page is the last one — stop rather
        # than paying an extra empty-page request.
        if total_pages is None and len(data) < PAGE_SIZE:
            self._has_next_page = False


def _client_config(api_token: str) -> ClientConfig:
    return {
        "base_url": CLOUDFLARE_BASE_URL,
        "auth": {"type": "bearer", "token": api_token},
        "paginator": CloudflarePaginator(),
    }


def _list_resource(name: str, path: str) -> EndpointResource:
    return {
        "name": name,
        "endpoint": {
            "path": path,
            "params": {"per_page": PAGE_SIZE},
            "data_selector": "result",
        },
    }


def _flat_resource(
    api_token: str, endpoint: str, config: CloudflareEndpointConfig, team_id: int, job_id: str
) -> Resource:
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_token),
        "resource_defaults": {},
        "resources": [_list_resource(endpoint, config.path)],
    }
    return rest_api_resource(rest_config, team_id, job_id, None)


def _zone_fanout_resource(
    api_token: str, endpoint: str, config: CloudflareEndpointConfig, team_id: int, job_id: str
) -> Resource:
    assert config.parent_key is not None, (
        f"Zone-scoped endpoint '{endpoint}' must define parent_key in CLOUDFLARE_ENDPOINTS"
    )
    parent_key = config.parent_key

    child: EndpointResource = {
        "name": endpoint,
        "endpoint": {
            "path": config.path,
            "params": {
                "per_page": PAGE_SIZE,
                "zone_id": {"type": "resolve", "resource": "zones", "field": "id"},
            },
            "data_selector": "result",
            "response_actions": [{"status_code": status, "action": "ignore"} for status in ZONE_SKIP_STATUS_CODES],
        },
        "include_from_parent": ["id"],
    }
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_token),
        "resource_defaults": {},
        "resources": [_list_resource("zones", "/zones"), child],
    }
    resources = {r.name: r for r in rest_api_resources(rest_config, team_id, job_id, None)}
    # A zone row without an id can't be fanned out — skip it rather than failing the stream.
    resources["zones"].add_filter(lambda zone: bool(zone.get("id")))

    def _rename_parent_key(row: dict[str, Any]) -> dict[str, Any]:
        if "_zones_id" in row:
            row[parent_key] = row.pop("_zones_id")
        return row

    return resources[endpoint].add_map(_rename_parent_key)


def validate_credentials(api_token: str) -> bool:
    """Confirm the API token is valid with Cloudflare's token verify endpoint."""
    try:
        response = make_tracked_session(redact_values=(api_token,)).get(
            f"{CLOUDFLARE_BASE_URL}/user/tokens/verify",
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=10,
        )
        return response.status_code == 200 and bool(response.json().get("success"))
    except Exception:
        return False


def cloudflare_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    config = CLOUDFLARE_ENDPOINTS[endpoint]

    if config.zone_scoped:
        resource = _zone_fanout_resource(api_token, endpoint, config, team_id, job_id)
    else:
        resource = _flat_resource(api_token, endpoint, config, team_id, job_id)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )
