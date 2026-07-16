import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.secureframe.settings import SECUREFRAME_ENDPOINTS

BASE_URLS = {
    "us": "https://api.secureframe.com",
    "uk": "https://api-uk.secureframe.com",
}
DEFAULT_REGION = "us"
# Secureframe caps list pages at 100 items (also the documented default).
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5


class SecureframeRetryableError(Exception):
    pass


@dataclasses.dataclass
class SecureframeResumeConfig:
    page: int


def _base_url(region: str) -> str:
    return BASE_URLS.get(region, BASE_URLS[DEFAULT_REGION])


def _get_headers(api_key: str, api_secret: str) -> dict[str, str]:
    # Secureframe authenticates with the API key and secret joined by a space (no scheme prefix).
    return {
        "Authorization": f"{api_key} {api_secret}",
        "Accept": "application/json",
    }


def _build_url(region: str, path: str, page: int) -> str:
    params = {"page": page, "per_page": PAGE_SIZE}
    return f"{_base_url(region)}{path}?{urlencode(params)}"


def _flatten_resource(obj: Any) -> Optional[dict[str, Any]]:
    """Flatten a JSON:API-style resource envelope into a plain row dict.

    Secureframe wraps each resource as ``{"data": {"id", "type", "attributes": {...}}}``;
    the attributes already carry ``id`` per the API spec, but we backfill it from the
    envelope defensively. Plain dicts pass through untouched.
    """
    if not isinstance(obj, dict):
        return None

    node = obj.get("data", obj)
    if not isinstance(node, dict):
        return None

    attributes = node.get("attributes")
    if isinstance(attributes, dict):
        row = dict(attributes)
        if "id" not in row and node.get("id") is not None:
            row["id"] = node["id"]
        return row

    return node


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict) and isinstance(payload.get("data"), list):
        items = payload["data"]
    else:
        items = []

    return [row for row in (_flatten_resource(item) for item in items) if row is not None]


def _probe_endpoint(api_key: str, api_secret: str, region: str, path: str) -> int:
    """Fetch a single row from an endpoint and return the HTTP status code."""
    params = {"page": 1, "per_page": 1}
    response = make_tracked_session().get(
        f"{_base_url(region)}{path}?{urlencode(params)}",
        headers=_get_headers(api_key, api_secret),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    return response.status_code


def validate_credentials(api_key: str, api_secret: str, region: str, endpoint: str | None = None) -> tuple[bool, bool]:
    """Probe the API and return ``(authenticated, authorized)``.

    Secureframe returns 401 for a bad key/secret pair and 403 when the pair is valid but
    the key's RBAC role can't read the probed resource. At source-create a 403 is
    acceptable (users may only grant the scopes they intend to sync), so callers get both
    signals. Any other failure counts as unauthenticated.
    """
    path = SECUREFRAME_ENDPOINTS[endpoint].path if endpoint else "/users"
    try:
        status = _probe_endpoint(api_key, api_secret, region, path)
    except Exception:
        return False, False

    if status == 200:
        return True, True
    if status == 403:
        return True, False
    return False, False


def get_endpoint_permissions(api_key: str, api_secret: str, region: str, endpoints: list[str]) -> dict[str, str | None]:
    permissions: dict[str, str | None] = {}
    for endpoint in endpoints:
        config = SECUREFRAME_ENDPOINTS.get(endpoint)
        if config is None:
            permissions[endpoint] = None
            continue
        try:
            status = _probe_endpoint(api_key, api_secret, region, config.path)
        except Exception:
            # A throttle, 5xx, or network blip is not a denial — report reachable.
            permissions[endpoint] = None
            continue
        if status in (401, 403):
            permissions[endpoint] = (
                f"Your API key's role does not have permission to read {endpoint}. "
                "Update the role's permissions in Secureframe, or deselect this table."
            )
        else:
            permissions[endpoint] = None
    return permissions


def get_rows(
    api_key: str,
    api_secret: str,
    region: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SecureframeResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = SECUREFRAME_ENDPOINTS[endpoint]
    headers = _get_headers(api_key, api_secret)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        page = max(resume_config.page, 1)
        logger.debug(f"Secureframe: resuming {endpoint} from page {page}")
    else:
        page = 1

    @retry(
        retry=retry_if_exception_type((SecureframeRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(page_url: str) -> Any:
        response = make_tracked_session().get(page_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        # Secureframe doesn't publish rate limits; back off on 429 and transient 5xx.
        if response.status_code == 429 or response.status_code >= 500:
            raise SecureframeRetryableError(
                f"Secureframe API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"Secureframe API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        url = _build_url(region, config.path, page)
        payload = fetch_page(url)
        rows = _extract_rows(payload)

        # The API exposes no page-count metadata, so pagination terminates on the first
        # empty page. A short page could just mean the server capped per_page below what
        # we asked for, so it does not end the scan.
        if not rows:
            break

        yield rows

        page += 1
        resumable_source_manager.save_state(SecureframeResumeConfig(page=page))


def secureframe_source(
    api_key: str,
    api_secret: str,
    region: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SecureframeResumeConfig],
) -> SourceResponse:
    config = SECUREFRAME_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            api_secret=api_secret,
            region=region,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=[config.primary_key],
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
