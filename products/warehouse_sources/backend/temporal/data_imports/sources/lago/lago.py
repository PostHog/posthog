"""Lago transport layer.

Lago is an open-source usage-based billing platform offered both as Lago Cloud
(``https://api.getlago.com``) and self-hosted (a customer-supplied host), so the API base URL
must be configurable. Auth is a single Bearer API key. List endpoints are page-number paginated
(``page`` / ``per_page``) and wrap their records under a resource key alongside a ``meta`` object
that carries ``next_page``.

Every stream is full-refresh. Lago's REST API exposes no universal server-side ``created_at`` /
``updated_at`` cursor across resources — only a handful of endpoints offer ad-hoc date filters
(e.g. ``issuing_date_from`` on invoices) that filter on a business date rather than a monotonic
record-creation timestamp, so they are unsafe to treat as an incremental cursor. Incremental sync
can be layered on later for a specific endpoint once its server-side filter is verified against the
live API.
"""

import re
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.lago.settings import (
    LAGO_ENDPOINTS,
    LagoEndpointConfig,
)

DEFAULT_API_HOST = "https://api.getlago.com"
API_VERSION_PATH = "/api/v1"

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
MAX_RETRY_AFTER_SECONDS = 60

HOST_NOT_ALLOWED_ERROR = "Lago API URL is not allowed"


class LagoRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LagoHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class LagoResumeConfig:
    # The next page to fetch on resume. Persisted after each page is yielded, so a crash before
    # this write leaves the previous value in place and the last page is re-yielded (Lago merges
    # dedupe on `lago_id`).
    next_page: int


def normalize_base_url(api_url: Optional[str]) -> str:
    """Turn whatever the user typed into a ``<scheme>://<host>/api/v1`` base URL.

    Blank → Lago Cloud. Accepts bare hosts (``billing.example.com``), full URLs with or without a
    scheme, and values that already include the ``/api/v1`` suffix.
    """
    raw = (api_url or "").strip()
    if not raw:
        raw = DEFAULT_API_HOST
    if not re.match(r"^https?://", raw, flags=re.IGNORECASE):
        raw = f"https://{raw}"
    raw = raw.rstrip("/")
    # Drop a trailing version segment the user may have pasted in, then re-add the version we target.
    raw = re.sub(r"/api/v\d+$", "", raw)
    return f"{raw}{API_VERSION_PATH}"


def _host_of(base_url: str) -> str:
    return (urlparse(base_url).hostname or "").lower()


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def validate_credentials(
    api_url: Optional[str], api_key: str, schema_name: Optional[str] = None, team_id: Optional[int] = None
) -> tuple[bool, str | None]:
    """Probe a cheap list endpoint to confirm the Bearer token is genuine.

    At source-create (``schema_name is None``) a 403 is accepted: the token is valid but may lack
    permission for this particular probe. A scoped probe (``schema_name`` set) treats 403 as a hard
    failure.
    """
    base_url = normalize_base_url(api_url)
    host = _host_of(base_url)

    if not host:
        return False, "Invalid Lago API URL"

    # The host is fully customer-controlled for self-hosted deployments, so block hosts that resolve
    # to private/internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(host, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    url = f"{base_url}/customers?{urlencode({'per_page': 1, 'page': 1})}"
    try:
        # Don't follow redirects: the validated host could 3xx to an internal address, defeating
        # the host check above (SSRF).
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10, allow_redirects=False)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.is_redirect or response.is_permanent_redirect:
        return False, HOST_NOT_ALLOWED_ERROR

    if response.status_code == 200:
        return True, None

    if response.status_code == 401:
        return False, "Invalid Lago API key"

    if response.status_code == 403:
        if schema_name is None:
            # Valid token, missing permission for this probe — let source creation through.
            return True, None
        return False, "Lago API key lacks the required permissions for this endpoint"

    try:
        body = response.json()
        return False, body.get("error", response.text)
    except Exception:
        return False, response.text


def _parse_retry_after(response: requests.Response) -> float | None:
    """Honor a whole-second ``Retry-After`` on 429. HTTP-date forms are ignored."""
    raw = response.headers.get("Retry-After")
    if raw and raw.strip().isdigit():
        return min(float(raw.strip()), MAX_RETRY_AFTER_SECONDS)
    return None


def _retry_wait(retry_state: RetryCallState) -> float:
    """Use a server-provided Retry-After when present, else exponential backoff."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, LagoRetryableError) and exc.retry_after is not None:
        return exc.retry_after
    return wait_exponential_jitter(initial=1, max=30)(retry_state)


def get_rows(
    api_url: Optional[str],
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LagoResumeConfig],
    team_id: int,
) -> Iterator[list[dict[str, Any]]]:
    config: LagoEndpointConfig = LAGO_ENDPOINTS[endpoint]
    base_url = normalize_base_url(api_url)
    host = _host_of(base_url)

    # Re-check at run time (not just at source-create) in case the URL was edited or now resolves
    # to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    host_ok, host_err = _is_host_safe(host, team_id)
    if not host_ok:
        raise LagoHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

    headers = _get_headers(api_key)
    request_url = f"{base_url}{config.path}"

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume_config.next_page if resume_config is not None else 1
    if resume_config is not None:
        logger.debug(f"Lago: resuming {endpoint} from page {page}")

    @retry(
        retry=retry_if_exception_type((LagoRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=_retry_wait,
        reraise=True,
    )
    def fetch_page(page_number: int) -> requests.Response:
        query = urlencode({"page": page_number, "per_page": config.page_size})
        # Don't follow redirects: an attacker-controlled host could 3xx to an internal address,
        # bypassing the host validation done before the request (SSRF).
        response = make_tracked_session().get(
            f"{request_url}?{query}", headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False
        )

        if response.status_code == 429 or response.status_code >= 500:
            retry_after = _parse_retry_after(response) if response.status_code == 429 else None
            raise LagoRetryableError(
                f"Lago API error (retryable): status={response.status_code}, url={request_url}",
                retry_after=retry_after,
            )

        # A 3xx isn't an error status (`response.ok` is True), so reject it explicitly rather than
        # silently parsing the redirect body as data.
        if response.is_redirect or response.is_permanent_redirect:
            raise LagoHostNotAllowedError(
                f"Lago API returned an unexpected redirect (status={response.status_code}); refusing to follow it"
            )

        if not response.ok:
            logger.error(f"Lago API error: status={response.status_code}, body={response.text}, url={request_url}")
            response.raise_for_status()

        return response

    while True:
        response = fetch_page(page)
        body = response.json()
        rows = body.get(config.data_key) or []
        if not isinstance(rows, list) or not rows:
            break

        yield rows

        next_page = (body.get("meta") or {}).get("next_page")
        if not next_page:
            break
        page = int(next_page)

        # Checkpoint AFTER yielding the page: a crash before this write re-yields the page on resume
        # (dedupes on the primary key), while a crash after it resumes at the next page.
        resumable_source_manager.save_state(LagoResumeConfig(next_page=page))


def lago_source(
    api_url: Optional[str],
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LagoResumeConfig],
    team_id: int,
) -> SourceResponse:
    config = LAGO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_url=api_url,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            team_id=team_id,
        ),
        primary_keys=[config.primary_key],
        # Full-refresh replace: Lago exposes no `sort` param and no incremental cursor, so there is
        # no watermark to checkpoint. The default ascending mode is harmless here.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
