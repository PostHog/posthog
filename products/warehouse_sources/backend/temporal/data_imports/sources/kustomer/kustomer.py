import re
import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.kustomer.settings import KUSTOMER_ENDPOINTS

# Kustomer list pages cap at 100 items.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Default rate limit is 300 calls/min; 429s carry x-ratelimit headers but
# exponential backoff is sufficient.
MAX_RETRY_ATTEMPTS = 5


class KustomerRetryableError(Exception):
    pass


@dataclasses.dataclass
class KustomerResumeConfig:
    # Kustomer paginates via a JSON:API `links.next` URL (absolutized against
    # the org host), so the URL is all we persist.
    next_url: str


def _get_session(api_key: str) -> requests.Session:
    return make_tracked_session(headers={"Authorization": f"Bearer {api_key}"}, redact_values=(api_key,))


def _clean_org_name(org_name: str) -> str:
    """Accept either the bare org subdomain or a pasted full domain/URL."""
    org = org_name.strip().removeprefix("https://").removeprefix("http://")
    org = org.split(".")[0].split("/")[0]
    if not re.fullmatch(r"[a-zA-Z0-9-]+", org):
        raise ValueError(f"Invalid Kustomer organization name: {org_name}")
    return org


def _base_url(org_name: str) -> str:
    return f"https://{_clean_org_name(org_name)}.api.kustomerapp.com"


def _ensure_same_origin(url: str, base_url: str) -> str:
    """Reject pagination/resume URLs that leave the org host.

    `links.next` is server-controlled and `urljoin` follows absolute URLs
    verbatim, so a tampered response could otherwise point our authenticated
    request (which carries the API key in its Bearer header) at an external host
    and leak the key. Compare the full origin (scheme + netloc), not a prefix, so
    look-alike hosts like `org.api.kustomerapp.com.evil.com` are rejected too."""
    parsed, base = urlparse(url), urlparse(base_url)
    if (parsed.scheme, parsed.netloc) != (base.scheme, base.netloc):
        raise ValueError(f"Kustomer URL {url!r} does not stay on the expected host {base_url!r}")
    return url


def validate_credentials(org_name: str, api_key: str) -> bool:
    """Confirm the API key and org are valid with a cheap one-customer probe.

    Role-scoped keys may lack individual read grants (403); only 401 means the
    key itself is bad."""
    try:
        response = _get_session(api_key).get(
            f"{_base_url(org_name)}/v1/customers?{urlencode({'page[size]': 1})}",
            timeout=10,
        )
        return response.status_code != 401
    except Exception:
        return False


def get_rows(
    org_name: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[KustomerResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = KUSTOMER_ENDPOINTS[endpoint]
    session = _get_session(api_key)
    base_url = _base_url(org_name)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        # Re-validate the persisted URL so a tampered Redis state can't redirect
        # our authenticated request off-host.
        url: str = _ensure_same_origin(resume_config.next_url, base_url)
        logger.debug(f"Kustomer: resuming {endpoint} from URL: {url}")
    else:
        url = f"{base_url}{config.path}?{urlencode({'page[size]': PAGE_SIZE})}"

    @retry(
        retry=retry_if_exception_type((KustomerRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        response = session.get(page_url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise KustomerRetryableError(
                f"Kustomer API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"Kustomer API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(url)
        items = data.get("data", []) or []

        if items:
            yield items

        next_link = (data.get("links") or {}).get("next")
        if not next_link or not items:
            break

        # links.next is typically a relative path; absolutize against the org
        # host and pin to that origin so an absolute off-host URL can't leak the
        # API key.
        next_url = _ensure_same_origin(urljoin(base_url, next_link), base_url)
        # Save state AFTER yielding the page so a crash re-yields the last page
        # (merge dedupes on primary key) rather than skipping it.
        resumable_source_manager.save_state(KustomerResumeConfig(next_url=next_url))
        url = next_url


def kustomer_source(
    org_name: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[KustomerResumeConfig],
) -> SourceResponse:
    config = KUSTOMER_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            org_name=org_name,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )
