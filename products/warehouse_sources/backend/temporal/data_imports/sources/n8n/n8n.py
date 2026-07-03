import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.n8n.settings import (
    N8N_API_PATH,
    N8N_ENDPOINTS,
    PAGE_SIZE,
)

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5


class N8nRetryableError(Exception):
    pass


@dataclasses.dataclass
class N8nResumeConfig:
    # The `nextCursor` token to fetch the next page. None means "start from the
    # first page" — used both on a fresh sync and when the bookmark predates any page.
    next_cursor: Optional[str] = None


def normalize_host(host: str) -> str:
    """Normalize the instance URL and reject anything that isn't plain http(s).

    Accepts either a bare host (`myinstance.app.n8n.cloud`) or a full URL, with or
    without the `/api/v1` suffix, and returns the instance origin (no trailing slash).
    """
    host = host.strip()
    if not host:
        raise ValueError("n8n host is required")
    if "://" not in host:
        host = f"https://{host}"
    host = host.rstrip("/")
    # Tolerate a pasted API base URL by trimming a trailing /api/v1.
    if host.endswith(N8N_API_PATH):
        host = host[: -len(N8N_API_PATH)]
    parsed = urlparse(host)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"Invalid n8n host: {host}")
    # SSRF guard: urlparse treats a backslash as userinfo and an "@" as a userinfo
    # separator, but urllib3/requests treat the backslash as an authority separator, so
    # `http://127.0.0.1\@example.com` validates as example.com yet connects to 127.0.0.1.
    # A legitimate instance URL has no userinfo, so reject either construct outright.
    if "\\" in host or "%5c" in host.lower() or "@" in parsed.netloc:
        raise ValueError(f"Invalid n8n host: {host}")
    return host


def hostname_of(host: str) -> str:
    return urlparse(normalize_host(host)).hostname or ""


def _base_url(host: str) -> str:
    return f"{normalize_host(host)}{N8N_API_PATH}"


def _get_headers(api_key: str) -> dict[str, str]:
    return {"X-N8N-API-KEY": api_key, "Accept": "application/json"}


def _get_session(api_key: str) -> requests.Session:
    # `host` is user-supplied, so pin redirects off so validation and the outbound
    # request stay on the same target (SSRF defense-in-depth). Redact the key from logs.
    return make_tracked_session(redact_values=(api_key,), allow_redirects=False)


def _build_url(base_url: str, params: dict[str, Any]) -> str:
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


@retry(
    retry=retry_if_exception_type(
        (
            N8nRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise N8nRetryableError(f"n8n API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"n8n API error: status={response.status_code}, body={response.text[:500]}, url={url}")
        response.raise_for_status()

    body = response.json()
    return body if isinstance(body, dict) else {"data": body}


def validate_credentials(host: str, api_key: str) -> bool:
    """Confirm the instance is reachable and the key is accepted.

    Probes /workflows with limit=1 — the most broadly-available scope on an API key.
    """
    try:
        url = _build_url(f"{_base_url(host)}/workflows", {"limit": 1})
        response = _get_session(api_key).get(url, headers=_get_headers(api_key), timeout=15)
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    host: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[N8nResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = N8N_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    session = _get_session(api_key)

    base_params: dict[str, Any] = {"limit": PAGE_SIZE, **config.extra_params}
    endpoint_url = f"{_base_url(host)}{config.path}"

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor: Optional[str] = resume_config.next_cursor if resume_config is not None else None
    if cursor:
        logger.debug(f"n8n: resuming {endpoint} from cursor")

    while True:
        params = dict(base_params)
        if cursor:
            params["cursor"] = cursor

        data = _fetch_page(session, _build_url(endpoint_url, params), headers, logger)

        # `data` is the required envelope field; fail fast if a 200 response ever omits it.
        items = data["data"]
        next_cursor = data.get("nextCursor")

        if items:
            yield items

        if not next_cursor:
            break

        cursor = next_cursor
        # Save state AFTER yielding so a crash re-yields the in-flight page rather
        # than skipping it — merge dedupes on the primary key.
        resumable_source_manager.save_state(N8nResumeConfig(next_cursor=cursor))


def n8n_source(
    host: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[N8nResumeConfig],
) -> SourceResponse:
    config = N8N_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            host=host,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=list(config.primary_keys),
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
