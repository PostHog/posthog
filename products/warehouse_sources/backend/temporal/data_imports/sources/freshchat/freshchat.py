import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.freshchat.settings import (
    FRESHCHAT_ENDPOINTS,
    PER_PAGE,
    PRIMARY_KEYS,
    FreshchatEndpointConfig,
)

REQUEST_TIMEOUT = 60
VALIDATE_TIMEOUT = 10
MAX_RETRIES = 5
MAX_RETRY_WAIT = 60.0

# All documented Freshchat API hosts live under these Freshworks-owned domains: account
# subdomains and regional hosts (api.freshchat.com, api.eu.freshchat.com, ...) under
# freshchat.com, Freshsales Suite accounts under myfreshworks.com.
ALLOWED_HOST_SUFFIXES = ("freshchat.com", "myfreshworks.com")

HOST_NOT_ALLOWED_ERROR = "Freshchat domain is not allowed"

_EXPONENTIAL_WAIT = wait_exponential_jitter(initial=1, max=MAX_RETRY_WAIT)


class FreshchatRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class FreshchatHostNotAllowedError(Exception):
    pass


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header. Freshworks APIs send an integer number of seconds."""
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _retry_wait(retry_state: RetryCallState) -> float:
    """Honor a server-provided Retry-After (capped); otherwise fall back to exponential jitter."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, FreshchatRetryableError) and exc.retry_after is not None:
        return min(exc.retry_after, MAX_RETRY_WAIT)
    return _EXPONENTIAL_WAIT(retry_state)


@dataclasses.dataclass
class FreshchatResumeConfig:
    # The next page number to fetch. Freshchat uses page/items_per_page pagination, so a single
    # integer is enough to pick back up. Endpoints are full refresh (no time window), so re-entering
    # a page and deduping on the primary key is safe.
    page: int


def normalize_domain(domain: str) -> str:
    """Normalize the Freshchat host the user supplied.

    Accepts a bare account name ("acme" -> "acme.freshchat.com"), a full host
    ("acme.freshchat.com", "acme.myfreshworks.com", "api.eu.freshchat.com"), or a URL with a
    scheme/path. Freshchat's base host varies by account and data center, so we keep whatever
    host the user gives and only default the domain when they pass a bare account name.
    """
    d = domain.strip().lower().removeprefix("https://").removeprefix("http://")
    d = d.split("/")[0].strip().rstrip("/")
    if "." not in d:
        d = f"{d}.freshchat.com"
    return d


def is_allowed_host(host: str) -> bool:
    """Only Freshworks-owned hosts are reachable: account subdomains and regional API hosts live
    under freshchat.com, Freshsales Suite accounts under myfreshworks.com. The domain is fully
    customer-controlled, so anything else (e.g. an internal hostname) is refused — the stored
    token plus scheduled syncs would otherwise let a user aim authenticated GETs at arbitrary
    hosts (SSRF)."""
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in ALLOWED_HOST_SUFFIXES)


def _base_url(domain: str) -> str:
    return f"https://{normalize_domain(domain)}/v2"


def _get_headers(api_key: str) -> dict[str, str]:
    # Freshchat authenticates with a long-lived Bearer token. Accept is required so the API
    # returns JSON rather than an HTML error page.
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


def build_base_params(config: FreshchatEndpointConfig) -> dict[str, str]:
    """Query params shared across every page of one sync (everything except `page`)."""
    params: dict[str, str] = {}
    if config.paginated:
        params["items_per_page"] = str(PER_PAGE)
        # Explicit stable sort so page boundaries don't skip/duplicate rows if the API's implicit
        # default order shifts while we page.
        params["sort_order"] = "asc"
    params.update(config.extra_params)
    return params


def extract_items(data: Any, config: FreshchatEndpointConfig) -> list[dict]:
    """Freshchat's envelope is inconsistent: most lists wrap under a resource key, some return a
    bare array, and single-object endpoints return one object. Handle all three shapes."""
    if config.data_key and isinstance(data, dict):
        value = data.get(config.data_key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            return [value]
    if isinstance(data, list):
        return data
    if config.single_object and isinstance(data, dict):
        return [data]
    return []


def _has_next_page(data: Any, items: list[dict], page: int) -> bool:
    if not items:
        return False
    if isinstance(data, dict):
        pagination = data.get("pagination")
        if isinstance(pagination, dict) and isinstance(pagination.get("total_pages"), int):
            total_pages = pagination["total_pages"]
            current = pagination.get("current_page")
            current_page = current if isinstance(current, int) else page
            return current_page < total_pages
        links = data.get("links")
        if isinstance(links, dict):
            next_page = links.get("next_page")
            return isinstance(next_page, dict) and bool(next_page.get("href"))
    # No usable pagination metadata -> a full page implies there may be more.
    return len(items) >= PER_PAGE


def get_rows(
    api_key: str,
    domain: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FreshchatResumeConfig],
) -> Iterator[list[dict]]:
    config = FRESHCHAT_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)

    # Re-check at run time (not just at source-create) so an edited or previously-saved domain
    # can't aim the stored token at a non-Freshworks host (SSRF).
    if not is_allowed_host(normalize_domain(domain)):
        raise FreshchatHostNotAllowedError(HOST_NOT_ALLOWED_ERROR)

    base = _base_url(domain)
    base_params = build_base_params(config)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume is not None else 1
    if resume is not None:
        logger.debug(f"Freshchat: resuming {endpoint} from page {page}")

    # One session reused across pages so urllib3 keeps the connection alive. `redact_values` masks
    # the token from captured HTTP samples: it rides in the Authorization header, which the
    # name-based sample scrubbers don't recognise.
    session = make_tracked_session(redact_values=(api_key,))

    @retry(
        retry=retry_if_exception_type((FreshchatRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=_retry_wait,
        reraise=True,
    )
    def fetch_page(page_url: str) -> Any:
        # Don't follow redirects: the allowed host could 3xx to an arbitrary address, defeating
        # the host allowlist above (SSRF).
        response = session.get(page_url, headers=headers, timeout=REQUEST_TIMEOUT, allow_redirects=False)

        if response.is_redirect or response.is_permanent_redirect:
            raise FreshchatHostNotAllowedError(f"{HOST_NOT_ALLOWED_ERROR}: redirect from url={page_url}")

        # Freshchat throttles per plan tier with 429; honor Retry-After when present.
        if response.status_code == 429:
            raise FreshchatRetryableError(
                f"Freshchat API rate limited: url={page_url}",
                retry_after=_parse_retry_after(response.headers.get("Retry-After")),
            )

        if response.status_code >= 500:
            raise FreshchatRetryableError(
                f"Freshchat API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"Freshchat API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        params = dict(base_params)
        if config.paginated:
            params["page"] = str(page)
        url = f"{base}{config.path}?{urlencode(params)}" if params else f"{base}{config.path}"

        data = fetch_page(url)
        items = extract_items(data, config)
        if items:
            yield items

        if not config.paginated or not _has_next_page(data, items, page):
            break

        # Advance and save AFTER yielding so the just-written page is durable before we bookmark
        # the next one; a crash re-fetches from `page` and merge dedupes on the primary key.
        page += 1
        resumable_source_manager.save_state(FreshchatResumeConfig(page=page))


def freshchat_source(
    api_key: str,
    domain: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FreshchatResumeConfig],
) -> SourceResponse:
    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            domain=domain,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=PRIMARY_KEYS[endpoint],
        # All endpoints are full refresh; we page with an explicit ascending sort.
        sort_mode="asc",
    )


def validate_credentials(domain: str, api_key: str) -> Optional[int]:
    """Probe the Freshchat API. Returns the HTTP status code, or ``None`` on a connection error.

    Hits the account-configuration endpoint — the cheapest resource any valid token can read.
    """
    url = f"{_base_url(domain)}/accounts/configuration"
    try:
        # No redirects here either — a 3xx would otherwise carry the token to another host.
        response = make_tracked_session(redact_values=(api_key,)).get(
            url, headers=_get_headers(api_key), timeout=VALIDATE_TIMEOUT, allow_redirects=False
        )
    except Exception:
        return None

    return response.status_code
