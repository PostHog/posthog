"""Invoice Ninja transport layer.

Invoice Ninja is an open-source invoicing / billing platform offered both as the hosted SaaS
(``https://invoicing.co``) and self-hosted (a customer-supplied host), so the API base URL must be
configurable. Auth is a single ``X-API-TOKEN`` header; every request must also carry
``X-Requested-With: XMLHttpRequest`` (the API rejects requests without it) and be made over HTTPS.

List endpoints are page-number paginated (``page`` / ``per_page``) and wrap their records under a
top-level ``data`` key alongside a ``meta.pagination`` object that reports ``current_page`` and
``total_pages``.

Every stream is full-refresh. Invoice Ninja documents ``created_at`` / ``updated_at`` filters on its
index endpoints, but the timestamps are integer unix seconds and the ordering the API applies under
those filters could not be verified against the live API without a token — an unverified sort order
risks a corrupted incremental watermark on a mid-sync shutdown. Incremental sync can be layered on
per endpoint once its server-side filter and sort behaviour are verified with real credentials.
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
from products.warehouse_sources.backend.temporal.data_imports.sources.invoiceninja.settings import (
    INVOICENINJA_ENDPOINTS,
    InvoiceNinjaEndpointConfig,
)

DEFAULT_API_HOST = "https://invoicing.co"
API_VERSION_PATH = "/api/v1"

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
MAX_RETRY_AFTER_SECONDS = 60

HOST_NOT_ALLOWED_ERROR = "Invoice Ninja API URL is not allowed"


class InvoiceNinjaRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class InvoiceNinjaHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class InvoiceNinjaResumeConfig:
    # The next page to fetch on resume. Persisted after each page is yielded, so a crash before this
    # write leaves the previous value in place and the last page is re-yielded (merge dedupes on `id`).
    next_page: int


def normalize_base_url(base_url: Optional[str]) -> str:
    """Turn whatever the user typed into a ``<scheme>://<host>/api/v1`` base URL.

    Blank → the hosted Invoice Ninja SaaS. Accepts bare hosts (``invoices.example.com``), full URLs
    with or without a scheme, and values that already include the ``/api/v1`` suffix.
    """
    raw = (base_url or "").strip()
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


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "X-API-TOKEN": api_token,
        # Invoice Ninja rejects API requests that omit this header.
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json",
    }


def _is_invalid_token(response: requests.Response) -> bool:
    """A 403 from Invoice Ninja means a bad token — its body reads ``{"message": "Invalid token"}``.

    Enterprise plans can also restrict a token to a subset of entities, which surfaces as a 403 without
    that message; those are treated as a missing permission rather than a bad token.
    """
    try:
        message = (response.json() or {}).get("message", "")
    except Exception:
        message = response.text or ""
    return "invalid token" in message.lower()


def validate_credentials(
    base_url: Optional[str], api_token: str, schema_name: Optional[str] = None, team_id: Optional[int] = None
) -> tuple[bool, str | None]:
    """Probe a cheap list endpoint to confirm the API token is genuine.

    A bad Invoice Ninja token returns 403 ``{"message": "Invalid token"}``, so — unlike sources whose
    403 means "valid token, missing scope" — a 403 carrying that message is always a hard failure. A
    403 *without* it (an entity-restricted enterprise token) is accepted at source-create and only
    rejected for a scoped probe.
    """
    resolved_base_url = normalize_base_url(base_url)
    host = _host_of(resolved_base_url)

    if not host:
        return False, "Invalid Invoice Ninja API URL"

    # The host is fully customer-controlled for self-hosted deployments, so block hosts that resolve to
    # private/internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(host, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    url = f"{resolved_base_url}/clients?{urlencode({'per_page': 1, 'page': 1})}"
    try:
        # `redact_values` masks the token from captured HTTP samples: it rides in the `X-API-TOKEN`
        # header, which the transport's name-based denylist doesn't recognise. Don't follow redirects:
        # the validated host could 3xx to an internal address, defeating the host check above (SSRF).
        session = make_tracked_session(redact_values=(api_token,))
        response = session.get(url, headers=_get_headers(api_token), timeout=10, allow_redirects=False)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.is_redirect or response.is_permanent_redirect:
        return False, HOST_NOT_ALLOWED_ERROR

    if response.status_code == 200:
        return True, None

    if response.status_code == 401:
        return False, "Invalid Invoice Ninja API token"

    if response.status_code == 403:
        if _is_invalid_token(response):
            return False, "Invalid Invoice Ninja API token"
        if schema_name is None:
            # Valid token, restricted to a subset of entities — let source creation through.
            return True, None
        return False, "Your Invoice Ninja API token lacks permission for this endpoint"

    try:
        body = response.json()
        return False, body.get("message", response.text)
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
    if isinstance(exc, InvoiceNinjaRetryableError) and exc.retry_after is not None:
        return exc.retry_after
    return wait_exponential_jitter(initial=1, max=30)(retry_state)


def get_rows(
    base_url: Optional[str],
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[InvoiceNinjaResumeConfig],
    team_id: int,
) -> Iterator[list[dict[str, Any]]]:
    config: InvoiceNinjaEndpointConfig = INVOICENINJA_ENDPOINTS[endpoint]
    resolved_base_url = normalize_base_url(base_url)
    host = _host_of(resolved_base_url)

    # Re-check at run time (not just at source-create) in case the URL was edited or now resolves to an
    # internal address (SSRF / DNS rebinding). Only enforced on cloud.
    host_ok, host_err = _is_host_safe(host, team_id)
    if not host_ok:
        raise InvoiceNinjaHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

    headers = _get_headers(api_token)
    request_url = f"{resolved_base_url}{config.path}"

    # One session reused across every page (and retry) so urllib3 keeps the connection alive. It
    # redacts the token from captured HTTP samples — the token rides in the `X-API-TOKEN` header, which
    # the transport's name-based denylist doesn't recognise, so value-based masking is what covers it.
    session = make_tracked_session(redact_values=(api_token,))

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume_config.next_page if resume_config is not None else 1
    if resume_config is not None:
        logger.debug(f"Invoice Ninja: resuming {endpoint} from page {page}")

    @retry(
        retry=retry_if_exception_type((InvoiceNinjaRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=_retry_wait,
        reraise=True,
    )
    def fetch_page(page_number: int) -> requests.Response:
        query = urlencode({"page": page_number, "per_page": config.page_size})
        # Don't follow redirects: an attacker-controlled host could 3xx to an internal address,
        # bypassing the host validation done before the request (SSRF).
        response = session.get(
            f"{request_url}?{query}", headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False
        )

        if response.status_code == 429 or response.status_code >= 500:
            retry_after = _parse_retry_after(response) if response.status_code == 429 else None
            raise InvoiceNinjaRetryableError(
                f"Invoice Ninja API error (retryable): status={response.status_code}, url={request_url}",
                retry_after=retry_after,
            )

        # A 3xx isn't an error status (`response.ok` is True), so reject it explicitly rather than
        # silently parsing the redirect body as data.
        if response.is_redirect or response.is_permanent_redirect:
            raise InvoiceNinjaHostNotAllowedError(
                f"Invoice Ninja API returned an unexpected redirect (status={response.status_code}); "
                "refusing to follow it"
            )

        if not response.ok:
            logger.error(
                f"Invoice Ninja API error: status={response.status_code}, body={response.text}, url={request_url}"
            )
            response.raise_for_status()

        return response

    while True:
        response = fetch_page(page)
        body = response.json()
        rows = body.get("data") or []
        if not isinstance(rows, list) or not rows:
            break

        yield rows

        # Invoice Ninja wraps its Laravel/Fractal paginator under `meta.pagination`, reporting the
        # current/total page count and a `links.next` URL that is null on the last page. Treat either
        # signal as "more pages remain". If the pagination block is missing entirely (never the case
        # for a healthy index endpoint), stop rather than risk an unbounded loop.
        pagination = (body.get("meta") or {}).get("pagination") or {}
        current_page = pagination.get("current_page")
        total_pages = pagination.get("total_pages")
        has_next_link = bool((pagination.get("links") or {}).get("next"))
        more_by_count = bool(current_page and total_pages and int(current_page) < int(total_pages))
        if not (more_by_count or has_next_link):
            break
        page = (int(current_page) + 1) if current_page else page + 1

        # Checkpoint AFTER yielding the page: a crash before this write re-yields the page on resume
        # (dedupes on the primary key), while a crash after it resumes at the next page.
        resumable_source_manager.save_state(InvoiceNinjaResumeConfig(next_page=page))


def invoiceninja_source(
    base_url: Optional[str],
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[InvoiceNinjaResumeConfig],
    team_id: int,
) -> SourceResponse:
    config = INVOICENINJA_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            base_url=base_url,
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            team_id=team_id,
        ),
        primary_keys=[config.primary_key],
        # Full-refresh replace: no incremental cursor is enabled, so there is no watermark to
        # checkpoint. Invoice Ninja returns `created_at` / `updated_at` as integer unix seconds rather
        # than datetimes, so datetime partitioning isn't applied — see the module docstring.
        sort_mode="asc",
    )
