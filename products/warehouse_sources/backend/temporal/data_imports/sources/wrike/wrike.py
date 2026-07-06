import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode, urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.wrike.settings import (
    WRIKE_ENDPOINTS,
    WrikeEndpointConfig,
)

# Wrike serves each account from a region-specific host (www.wrike.com, app-us2.wrike.com,
# app-eu.wrike.com, ...). The user supplies their host; we only ever send the token to a
# *.wrike.com host to avoid being retargeted at an attacker-controlled or internal address.
WRIKE_HOST_SUFFIX = "wrike.com"
API_PATH = "/api/v4"
# Wrike caps paginated list pages at 1000 items.
PAGE_SIZE = 1000
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5


class WrikeRetryableError(Exception):
    pass


@dataclasses.dataclass
class WrikeResumeConfig:
    next_page_token: str


def _normalize_host(host: str) -> str:
    """Extract the bare hostname the credential would actually be sent to.

    The user-supplied value is parsed as a URL and reduced to its hostname, so a value
    carrying a path, query, port, or credentials (e.g. `evil.com?.wrike.com` or
    `internal.service/x.wrike.com`) can't smuggle a non-Wrike netloc past `is_host_valid`'s
    suffix check — `requests` would otherwise connect to `evil.com`/`internal.service`.
    Both validation and URL construction go through this, so the validated host and the
    connection target are always the same value."""
    candidate = host.strip().lower()
    if "://" not in candidate:
        candidate = f"//{candidate}"
    return urlsplit(candidate).hostname or ""


def is_host_valid(host: str) -> bool:
    """Only allow Wrike-owned hosts as the credential target (anti-SSRF)."""
    if not host:
        return False
    hostname = _normalize_host(host)
    return hostname == WRIKE_HOST_SUFFIX or hostname.endswith(f".{WRIKE_HOST_SUFFIX}")


def _base_url(host: str) -> str:
    return f"https://{_normalize_host(host)}{API_PATH}"


def _build_url(host: str, path: str, params: dict[str, Any]) -> str:
    clean_params = {key: value for key, value in params.items() if value is not None}
    base = f"{_base_url(host)}{path}"
    if not clean_params:
        return base
    return f"{base}?{urlencode(clean_params)}"


def _get_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


def validate_credentials(access_token: str, host: str) -> tuple[bool, str | None]:
    """Confirm the access token is genuine. `/contacts?me=true` is a cheap authenticated probe
    that returns the current user."""
    if not is_host_valid(host):
        return False, "Host must be a Wrike domain (e.g. www.wrike.com or app-us2.wrike.com)"

    url = _build_url(host, "/contacts", {"me": "true"})
    try:
        response = make_tracked_session().get(url, headers=_get_headers(access_token), timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Wrike access token"
    if response.status_code == 403:
        return False, "Wrike access token is missing the required permissions"

    return False, f"Wrike API error: status={response.status_code}"


def _initial_params(config: WrikeEndpointConfig) -> dict[str, Any]:
    return {"pageSize": PAGE_SIZE} if config.paginated else {}


def get_rows(
    access_token: str,
    host: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[WrikeResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = WRIKE_ENDPOINTS[endpoint]
    headers = _get_headers(access_token)

    if not is_host_valid(host):
        raise ValueError(f"Refusing to send Wrike credentials to non-Wrike host: {host}")

    resume_config = (
        resumable_source_manager.load_state() if config.paginated and resumable_source_manager.can_resume() else None
    )
    if resume_config is not None:
        url = _build_url(host, config.path, {"nextPageToken": resume_config.next_page_token})
        logger.debug(f"Wrike: resuming {endpoint} from saved nextPageToken")
    else:
        url = _build_url(host, config.path, _initial_params(config))

    @retry(
        retry=retry_if_exception_type((WrikeRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        response = make_tracked_session().get(page_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        # Wrike rate-limits around 400 req/min; 429s and transient 5xx are retried with backoff.
        if response.status_code == 429 or response.status_code >= 500:
            raise WrikeRetryableError(f"Wrike API error (retryable): status={response.status_code}, url={page_url}")

        if not response.ok:
            logger.error(f"Wrike API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(url)
        items = data.get("data", []) or []

        if items:
            yield items

        # Only the paginated endpoints return a nextPageToken; everything else is a single page.
        next_page_token = data.get("nextPageToken") if config.paginated else None
        if not next_page_token:
            break

        resumable_source_manager.save_state(WrikeResumeConfig(next_page_token=next_page_token))
        url = _build_url(host, config.path, {"nextPageToken": next_page_token})


def wrike_source(
    access_token: str,
    host: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[WrikeResumeConfig],
) -> SourceResponse:
    config = WRIKE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_token=access_token,
            host=host,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=[config.primary_key],
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
