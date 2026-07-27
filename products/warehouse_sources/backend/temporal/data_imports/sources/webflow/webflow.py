import dataclasses
from collections.abc import Callable
from typing import Any, Optional
from urllib.parse import quote

import requests

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    Endpoint,
    EndpointResource,
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.webflow.settings import (
    COLLECTION_SCHEMA_PREFIX,
    DEFAULT_PAGE_SIZE,
    WEBFLOW_BASE_URL,
    WEBFLOW_ENDPOINTS,
    WebflowEndpointConfig,
    collection_items_endpoint_config,
)


@dataclasses.dataclass
class WebflowResumeConfig:
    offset: int


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }


def _encode_path_segment(value: str) -> str:
    """Percent-encode a value before interpolating it into a URL path.

    ``site_id`` is a non-secret field a user can edit on an existing source while the
    saved ``api_token`` is preserved. Without encoding, a value containing ``/``, ``?``,
    or ``#`` could redirect the authenticated request to an unintended Webflow endpoint.
    Encoding with ``safe=""`` keeps every delimiter inside the single path segment.
    """
    return quote(value, safe="")


def _extract_items(data: Any, data_key: str) -> list[dict[str, Any]]:
    """Pull the list of records out of a Webflow list envelope.

    Webflow uses a per-resource envelope key (``sites``, ``collections``, ``items``,
    ``orders``, …) rather than a single consistent key. We try the configured key
    first, then fall back to the first list-valued, non-``pagination`` key so an
    unverified envelope guess degrades gracefully instead of silently dropping rows.
    """
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []

    value = data.get(data_key)
    if isinstance(value, list):
        return value

    for key, candidate in data.items():
        if key != "pagination" and isinstance(candidate, list):
            return candidate
    return []


def _flatten_map(config: WebflowEndpointConfig) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Merge a nested object up into the row root (e.g. products nest the product
    under a ``product`` key alongside ``skus``)."""

    def _map(item: dict[str, Any]) -> dict[str, Any]:
        if config.flatten_key and isinstance(item.get(config.flatten_key), dict):
            rest = {**item}
            flattened = rest.pop(config.flatten_key)
            return {**flattened, **rest}
        return item

    return _map


def validate_credentials(api_token: str, site_id: str, schema_name: Optional[str] = None) -> tuple[bool, str | None]:
    url = f"{WEBFLOW_BASE_URL}/sites/{_encode_path_segment(site_id)}"
    try:
        response = make_tracked_session(redact_values=(api_token,)).get(
            url, headers=_get_headers(api_token), timeout=10
        )
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None

    if response.status_code == 401:
        return False, "Invalid Webflow API token"

    # A 403 means the token is genuine but lacks the scope for this probe. Accept it
    # at source-create (schema_name is None) so users only need to grant scopes for
    # the resources they actually want to sync; sync-time 403s are caught by
    # get_non_retryable_errors instead.
    if response.status_code == 403:
        if schema_name is None:
            return True, None
        return False, "Your Webflow API token is missing the scope required for this resource"

    if response.status_code == 404:
        return False, f"Webflow site '{site_id}' was not found or is not accessible by this token"

    # A 400 means Webflow rejected the Site ID as malformed before looking it up — distinct from a
    # 404 for a well-formed but unknown/inaccessible id. Surface a clear message instead of leaking
    # Webflow's raw "Validation Error: ..." envelope.
    if response.status_code == 400:
        return (
            False,
            "The Webflow Site ID isn't valid. Check that you entered the Site ID (not the site name or URL) and try again.",
        )

    try:
        message = response.json().get("message", response.text)
    except ValueError:
        message = response.text
    return False, message


def list_collections(api_token: str, site_id: str) -> list[dict[str, Any]]:
    url = f"{WEBFLOW_BASE_URL}/sites/{_encode_path_segment(site_id)}/collections"
    response = make_tracked_session(redact_values=(api_token,)).get(url, headers=_get_headers(api_token), timeout=30)
    response.raise_for_status()
    return _extract_items(response.json(), "collections")


def _resolve_collection_id(api_token: str, site_id: str, schema_name: str) -> str:
    for collection in list_collections(api_token, site_id):
        slug = collection.get("slug")
        if slug and f"{COLLECTION_SCHEMA_PREFIX}{slug}" == schema_name:
            return collection["id"]
    raise ValueError(f"Webflow collection for schema '{schema_name}' was not found on site '{site_id}'")


def _endpoint_config_for_schema(api_token: str, site_id: str, schema_name: str) -> WebflowEndpointConfig:
    if schema_name in WEBFLOW_ENDPOINTS:
        return WEBFLOW_ENDPOINTS[schema_name]
    if schema_name.startswith(COLLECTION_SCHEMA_PREFIX):
        collection_id = _resolve_collection_id(api_token, site_id, schema_name)
        return collection_items_endpoint_config(collection_id)
    raise ValueError(f"Unknown Webflow schema '{schema_name}'")


def webflow_source(
    api_token: str,
    site_id: str,
    schema_name: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[WebflowResumeConfig],
) -> SourceResponse:
    config = _endpoint_config_for_schema(api_token, site_id, schema_name)

    path = config.path.format(site_id=_encode_path_segment(site_id)) if config.requires_site else config.path

    params: dict[str, Any] = {}
    if config.sort_by:
        params["sortBy"] = config.sort_by
        params["sortOrder"] = config.sort_order

    # Paginated list endpoints page with limit/offset and report the grand total under
    # `pagination.total`; single-object and non-paginated list endpoints are one request.
    if config.paginated:
        paginator: OffsetPaginator | SinglePagePaginator = OffsetPaginator(
            limit=DEFAULT_PAGE_SIZE, total_path="pagination.total"
        )
    else:
        paginator = SinglePagePaginator()

    endpoint: Endpoint = {
        "path": path,
        "params": params,
        # A single-object endpoint (/sites/{site_id}) has no list envelope; "$" wraps the
        # whole object into one row. List endpoints carry rows under a per-resource key.
        "data_selector": "$" if config.single_object else config.data_key,
    }

    resource_config: EndpointResource = {
        "name": schema_name,
        "endpoint": endpoint,
    }
    if config.flatten_key:
        resource_config["data_map"] = _flatten_map(config)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": WEBFLOW_BASE_URL,
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_token},
            "paginator": paginator,
        },
        "resource_defaults": {},
        "resources": [resource_config],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash
        # re-yields the last page (merge dedupes) rather than skipping it. The saved offset
        # already points at the next page to fetch.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(WebflowResumeConfig(offset=int(state["offset"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=schema_name,
        items=lambda: resource,
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )
