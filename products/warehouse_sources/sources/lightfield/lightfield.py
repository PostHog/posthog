from collections.abc import Callable, Iterable, Iterator
from typing import Any
from urllib.parse import quote

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import (
    create_response_hooks,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.lightfield.settings import (
    CUSTOM_OBJECTS_ENDPOINT,
    DEFINITION_ENDPOINTS,
    LIGHTFIELD_ENDPOINTS,
    LIGHTFIELD_PAGE_SIZE,
    STANDARD_DEFINITION_RESOURCES,
    LightfieldDefinitionResource,
    LightfieldEndpointConfig,
)

LIGHTFIELD_BASE_URL = "https://api.lightfield.app"
REQUEST_TIMEOUT_SECONDS = 30


def _version_headers(api_version: str) -> dict[str, str]:
    # Every Lightfield request must carry the dated `Lightfield-Version` header.
    return {
        "Lightfield-Version": api_version,
        "Accept": "application/json",
    }


def _client(api_key: str, api_version: str) -> RESTClient:
    return RESTClient(
        base_url=LIGHTFIELD_BASE_URL,
        headers=_version_headers(api_version),
        auth=BearerTokenAuth(token=api_key),
    )


def _object_path(object_type: str) -> str:
    return f"/v1/objects/{quote(object_type, safe='')}"


def _list_custom_object_types(client: RESTClient, *, tolerate_denied: bool) -> list[str]:
    # The definitions tables still sync the standard types when custom objects are not
    # available to the key or the workspace plan.
    hooks = (
        create_response_hooks([{"status_code": 403, "action": "ignore"}, {"status_code": 404, "action": "ignore"}])
        if tolerate_denied
        else None
    )
    return [
        str(item["objectType"])
        for page in client.paginate(
            path="/v1/objects", paginator=SinglePagePaginator(), data_selector="data", hooks=hooks
        )
        for item in page
        if item.get("objectType")
    ]


def _custom_object_records(client: RESTClient) -> Iterator[list[dict[str, Any]]]:
    for object_type in _list_custom_object_types(client, tolerate_denied=False):
        for page in client.paginate(
            path=_object_path(object_type),
            paginator=OffsetPaginator(limit=LIGHTFIELD_PAGE_SIZE, total_path="totalCount"),
            data_selector="data",
        ):
            yield [{**record, "objectType": object_type} for record in page]


def _definition_rows(client: RESTClient, definitions_key: str) -> Iterator[list[dict[str, Any]]]:
    resources = list(STANDARD_DEFINITION_RESOURCES) + [
        LightfieldDefinitionResource(object_type=object_type, path=f"{_object_path(object_type)}/definitions")
        for object_type in _list_custom_object_types(client, tolerate_denied=True)
    ]
    # Each type needs its own read scope, so a key without one skips that type.
    hooks = create_response_hooks([{"status_code": 403, "action": "ignore"}])
    for resource in resources:
        bodies = [
            body
            for page in client.paginate(path=resource.path, paginator=SinglePagePaginator(), hooks=hooks)
            for body in page
        ]
        # Yield one item per request, even an empty one: the pipeline checks for a worker shutdown on each item.
        yield [
            {**definition, "ownerObjectType": resource.object_type, "key": key}
            for body in bodies
            for key, definition in (body.get(definitions_key) or {}).items()
        ]


def _source_response(endpoint_config: LightfieldEndpointConfig, items: Callable[[], Iterable[Any]]) -> SourceResponse:
    partition_key = endpoint_config.partition_key
    return SourceResponse(
        name=endpoint_config.name,
        items=items,
        primary_keys=list(endpoint_config.primary_keys),
        partition_count=1 if partition_key else None,
        partition_size=1 if partition_key else None,
        partition_mode="datetime" if partition_key else None,
        partition_format="month" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
    )


def lightfield_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
) -> SourceResponse:
    endpoint_config = LIGHTFIELD_ENDPOINTS[endpoint]

    if endpoint == CUSTOM_OBJECTS_ENDPOINT:
        client = _client(api_key, api_version)
        return _source_response(endpoint_config, lambda: _custom_object_records(client))

    if endpoint in DEFINITION_ENDPOINTS:
        client = _client(api_key, api_version)
        definitions_key = DEFINITION_ENDPOINTS[endpoint]
        return _source_response(endpoint_config, lambda: _definition_rows(client, definitions_key))

    config: RESTAPIConfig = {
        "client": {
            "base_url": LIGHTFIELD_BASE_URL,
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
            "headers": _version_headers(api_version),
            # `totalCount` reflects the matching records at request time; the paginator also
            # stops on a short page, which the docs give as the canonical termination signal.
            "paginator": OffsetPaginator(limit=LIGHTFIELD_PAGE_SIZE, total_path="totalCount"),
        },
        "resource_defaults": {
            "write_disposition": "replace",
        },
        "resources": [
            {
                "name": endpoint_config.name,
                "table_name": endpoint_config.name,
                "write_disposition": "replace",
                "endpoint": {
                    "path": endpoint_config.path,
                    "data_selector": "data",
                },
                "table_format": "delta",
            }
        ],
    }

    resource = rest_api_resource(config, team_id, job_id, None)

    return _source_response(endpoint_config, lambda: resource)


def check_token(api_key: str, api_version: str) -> tuple[bool, list[str] | None, str | None]:
    """Probe `/v1/auth/validate` (no scope required). Returns (valid, granted scopes, error)."""
    session = make_tracked_session(redact_values=(api_key,))
    res = session.get(
        f"{LIGHTFIELD_BASE_URL}/v1/auth/validate",
        headers={"Authorization": f"Bearer {api_key}", **_version_headers(api_version)},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if res.status_code == 401:
        return False, None, "Invalid Lightfield API key. Check the key and try again."
    if res.status_code != 200:
        return False, None, f"Lightfield returned an unexpected status ({res.status_code}) while validating the key."

    body: dict[str, Any] = res.json()
    if not body.get("active", False):
        return False, None, "This Lightfield API key is no longer active. Generate a new key and reconnect."

    raw_scopes = body.get("scopes")
    scopes = [str(scope) for scope in raw_scopes] if isinstance(raw_scopes, list) else None
    return True, scopes, None
