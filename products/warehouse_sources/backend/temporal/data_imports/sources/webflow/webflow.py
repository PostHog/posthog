import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.webflow.settings import (
    COLLECTION_SCHEMA_PREFIX,
    DEFAULT_PAGE_SIZE,
    WEBFLOW_BASE_URL,
    WEBFLOW_ENDPOINTS,
    WebflowEndpointConfig,
    collection_items_endpoint_config,
)


class WebflowRetryableError(Exception):
    pass


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


def _normalize(item: dict[str, Any], config: WebflowEndpointConfig) -> dict[str, Any]:
    """Merge a nested object up into the row root (e.g. products nest the product
    under a ``product`` key alongside ``skus``)."""
    if config.flatten_key and isinstance(item.get(config.flatten_key), dict):
        rest = {**item}
        flattened = rest.pop(config.flatten_key)
        return {**flattened, **rest}
    return item


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


def _build_url(config: WebflowEndpointConfig, site_id: str, offset: int) -> str:
    path = config.path.format(site_id=_encode_path_segment(site_id)) if config.requires_site else config.path
    params: dict[str, Any] = {}
    if config.paginated:
        params["limit"] = DEFAULT_PAGE_SIZE
        params["offset"] = offset
    if config.sort_by:
        params["sortBy"] = config.sort_by
        params["sortOrder"] = config.sort_order
    base_url = f"{WEBFLOW_BASE_URL}{path}"
    return f"{base_url}?{urlencode(params)}" if params else base_url


def get_rows(
    api_token: str,
    site_id: str,
    schema_name: str,
    config: WebflowEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[WebflowResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    headers = _get_headers(api_token)
    session = make_tracked_session(headers=headers, redact_values=(api_token,))

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume_config.offset if resume_config else 0
    if resume_config:
        logger.debug(f"Webflow: resuming '{schema_name}' from offset {offset}")

    @retry(
        retry=retry_if_exception_type((WebflowRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(page_offset: int) -> Any:
        url = _build_url(config, site_id, page_offset)
        response = session.get(url, timeout=60)

        if response.status_code == 429 or response.status_code >= 500:
            raise WebflowRetryableError(f"Webflow API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Webflow API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(offset)
        if config.single_object:
            items = [data] if isinstance(data, dict) else _extract_items(data, config.data_key)
        else:
            items = _extract_items(data, config.data_key)

        if items:
            yield [_normalize(item, config) for item in items]

        if not config.paginated:
            break

        # Pagination metadata only lives on a dict envelope; a bare-list (or otherwise
        # non-dict) response has no pagination block, so fall through to short-page
        # termination instead of crashing on data.get(...).
        pagination = data.get("pagination") if isinstance(data, dict) else None
        total = pagination.get("total") if isinstance(pagination, dict) else None
        next_offset = offset + DEFAULT_PAGE_SIZE

        if total is not None:
            if next_offset >= total:
                break
        elif len(items) < DEFAULT_PAGE_SIZE:
            break

        offset = next_offset
        # Save after yielding the current page so a resume restarts at the next page.
        resumable_source_manager.save_state(WebflowResumeConfig(offset=offset))


def webflow_source(
    api_token: str,
    site_id: str,
    schema_name: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[WebflowResumeConfig],
) -> SourceResponse:
    config = _endpoint_config_for_schema(api_token, site_id, schema_name)

    return SourceResponse(
        name=schema_name,
        items=lambda: get_rows(
            api_token=api_token,
            site_id=site_id,
            schema_name=schema_name,
            config=config,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
