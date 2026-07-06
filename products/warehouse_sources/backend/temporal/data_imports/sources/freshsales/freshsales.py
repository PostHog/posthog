import re
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode

from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    HTTPError,
    ReadTimeout,
    RequestException,
)
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.freshsales.settings import (
    FRESHSALES_ENDPOINTS,
    FreshsalesEndpointConfig,
)

# Freshsales bundles live at https://<alias>.myfreshworks.com/crm/sales/api. We always template the
# host from a validated alias, so the stored API key can only ever be sent to a *.myfreshworks.com
# subdomain (defends against pointing the credential at an internal/attacker-controlled host).
FRESHSALES_DOMAIN_SUFFIX = "myfreshworks.com"
API_PATH = "/crm/sales/api"
_ALIAS_RE = re.compile(r"[a-z0-9][a-z0-9-]*")

DEFAULT_PAGE_SIZE = 100
REQUEST_TIMEOUT = 60
VALIDATE_TIMEOUT = 10
# Safety net so a broken termination signal can't loop forever. At 100 rows/page this covers 500k
# rows per endpoint; we log if it's ever hit so silent truncation is visible.
MAX_PAGES = 5000


class FreshsalesRetryableError(Exception):
    pass


@dataclasses.dataclass
class FreshsalesResumeConfig:
    next_page: int
    view_id: Optional[int] = None


def _normalize_alias(domain: str) -> str:
    value = (domain or "").strip().lower()
    value = value.removeprefix("https://").removeprefix("http://")
    # Tolerate a pasted full host/URL by keeping only the first subdomain label.
    alias = value.split("/")[0].split(".")[0]
    if not _ALIAS_RE.fullmatch(alias):
        raise ValueError(
            "Invalid Freshsales domain. Enter your bundle alias — the subdomain of your Freshsales URL "
            "(e.g. 'yourcompany' for yourcompany.myfreshworks.com)."
        )
    return alias


def _build_root(domain: str) -> str:
    return f"https://{_normalize_alias(domain)}.{FRESHSALES_DOMAIN_SUFFIX}{API_PATH}"


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Token token={api_key}",
        "Content-Type": "application/json",
    }


def _build_page_url(
    root: str,
    config: FreshsalesEndpointConfig,
    view_id: Optional[int],
    page: int,
    per_page: int = DEFAULT_PAGE_SIZE,
) -> str:
    if config.requires_view:
        path = f"{root}/{config.resource}/view/{view_id}"
    else:
        path = f"{root}/{config.resource}"

    params: dict[str, Any] = {"page": page, "per_page": per_page, **config.params}
    if config.sort:
        params["sort"] = config.sort
        params["sort_type"] = "asc"

    return f"{path}?{urlencode(params)}"


@retry(
    # Only transport hiccups and explicit 429/5xx are retried — HTTPError (a RequestException
    # subclass raised for 4xx by raise_for_status) must fail fast, not retry.
    retry=retry_if_exception_type((FreshsalesRetryableError, RequestsConnectionError, ReadTimeout)),
    stop=stop_after_attempt(5),
    # No Retry-After header is documented, and the default ceiling is 1000 req/hour, so back off
    # generously on 429/5xx.
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _fetch_page(session: Any, url: str, logger: FilteringBoundLogger) -> dict:
    response = session.get(url, timeout=REQUEST_TIMEOUT)

    if response.status_code == 429 or response.status_code >= 500:
        raise FreshsalesRetryableError(f"Freshsales API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Freshsales API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _resolve_view_id(session: Any, root: str, resource: str, logger: FilteringBoundLogger) -> Optional[int]:
    """View-based objects are listed through a saved "view". Discover its id via /<resource>/filters,
    preferring the account-wide "All ..." view."""
    url = f"{root}/{resource}/filters"
    try:
        data = _fetch_page(session, url, logger)
    except HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return None
        raise

    views = data.get("filters")
    if not isinstance(views, list) or not views:
        # Fall back to any list-shaped value in the response.
        views = next((v for v in data.values() if isinstance(v, list) and v), [])

    if not views:
        return None

    for view in views:
        name = str(view.get("name") or "").lower()
        if name.startswith("all"):
            return view.get("id")

    return views[0].get("id")


def get_rows(
    api_key: str,
    domain: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FreshsalesResumeConfig],
) -> Iterator[list[dict]]:
    config = FRESHSALES_ENDPOINTS[endpoint]
    root = _build_root(domain)
    session = make_tracked_session(headers=_get_headers(api_key), redact_values=(api_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    view_id: Optional[int] = None
    if config.requires_view:
        if resume is not None and resume.view_id is not None:
            view_id = resume.view_id
        else:
            view_id = _resolve_view_id(session, root, config.resource, logger)
            if view_id is None:
                if config.tolerate_missing:
                    logger.info(f"Freshsales: no view found for '{endpoint}', skipping (object not enabled)")
                    return
                raise ValueError(f"Freshsales: could not resolve a view for '{endpoint}'")

    page = resume.next_page if resume is not None else 1

    while page <= MAX_PAGES:
        url = _build_page_url(root, config, view_id, page)
        data = _fetch_page(session, url, logger)

        items = data.get(config.object_key) or []
        if not items:
            break

        yield items

        meta = data.get("meta") or {}
        total_pages = meta.get("total_pages")
        # `total_pages` is missing on some endpoints (e.g. appointments), so also stop on a short page.
        on_last_page = (total_pages is not None and page >= total_pages) or len(items) < DEFAULT_PAGE_SIZE
        if on_last_page:
            break

        page += 1
        # Save AFTER yielding so a crash re-yields the last page (merge/replace dedupes) rather than skipping it.
        resumable_source_manager.save_state(FreshsalesResumeConfig(next_page=page, view_id=view_id))
    else:
        logger.warning(f"Freshsales: reached max page cap ({MAX_PAGES}) for '{endpoint}'; results may be truncated")


def freshsales_source(
    api_key: str,
    domain: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FreshsalesResumeConfig],
) -> SourceResponse:
    config = FRESHSALES_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(api_key, domain, endpoint, logger, resumable_source_manager),
        primary_keys=config.primary_key,
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )


def check_credentials(
    api_key: str, domain: str, schema_name: Optional[str] = None
) -> tuple[bool, Optional[str], Optional[int]]:
    """Probe Freshsales credentials. Returns ``(ok, error_message, status_code)``.

    With ``schema_name=None`` (source create) it hits a cheap account-level endpoint. With a schema
    name it probes that specific endpoint so per-endpoint scope can be confirmed.
    """
    try:
        root = _build_root(domain)
    except ValueError as e:
        return False, str(e), None

    session = make_tracked_session(headers=_get_headers(api_key), redact_values=(api_key,))

    config = FRESHSALES_ENDPOINTS.get(schema_name) if schema_name else None
    if config is not None:
        if config.requires_view:
            url = f"{root}/{config.resource}/filters"
        else:
            url = _build_page_url(root, config, None, page=1, per_page=1)
    else:
        url = f"{root}/selector/owners"

    try:
        response = session.get(url, timeout=VALIDATE_TIMEOUT)
    except RequestException as e:
        return False, str(e), None

    if response.ok:
        return True, None, response.status_code

    if response.status_code == 401:
        return False, "Invalid Freshsales API key", 401
    if response.status_code == 403:
        return False, "Your Freshsales API key does not have permission to access this resource", 403
    if response.status_code == 404:
        return False, "Freshsales account not found. Please check your domain (bundle alias).", 404

    return False, f"Freshsales API returned status {response.status_code}", response.status_code
