from collections.abc import Iterable
from typing import Any, cast

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.acast.settings import (
    AUTH_ERROR,
    BASE_URL,
    ENDPOINTS,
    PERMISSION_ERROR,
    PRIMARY_KEYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    EndpointResource,
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse


def acast_source(api_key: str, endpoint: str, team_id: int, job_id: str) -> SourceResponse:
    endpoint_config = schema_for_resource(ENDPOINTS, endpoint)
    resources: list[str | EndpointResource] = (
        [ENDPOINTS["shows"], endpoint_config] if endpoint == "episodes" else [endpoint_config]
    )
    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "api_key", "name": "X-API-Key", "api_key": api_key, "location": "header"},
            "paginator": "single_page",
            "allow_redirects": False,
            "request_timeout": 60,
        },
        "resource_defaults": {
            "write_disposition": "replace",
            "endpoint": {"data_selector": "", "data_selector_required": True},
        },
        "resources": resources,
    }
    resource = next(
        resource
        for resource in rest_api_resources(config, team_id, job_id, db_incremental_field_last_value=None)
        if resource.name == endpoint
    )
    if endpoint == "episodes":
        resource.add_map(rename_parent_fields("shows", {"_id": "show_id"}))

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS[endpoint],
        sort_mode=None,
    )


def validate_credentials(api_key: str, team_id: int) -> tuple[bool, str | None]:
    try:
        items = cast(Iterable[Any], acast_source(api_key, "shows", team_id, "").items())
        next(iter(items), None)
    except HTTPError as error:
        if error.response is not None:
            if error.response.status_code == 401:
                return False, AUTH_ERROR
            if error.response.status_code == 403:
                return False, PERMISSION_ERROR
        raise
    return True, None
