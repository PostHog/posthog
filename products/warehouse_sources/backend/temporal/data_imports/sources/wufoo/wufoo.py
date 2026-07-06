import re
import base64
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.wufoo.settings import WUFOO_ENDPOINTS

# Wufoo enforces a per-account hostname, so only the subdomain label is user-supplied. Restricting
# it to host-safe characters keeps the request pinned to *.wufoo.com.
SUBDOMAIN_REGEX = re.compile(r"^[a-zA-Z0-9-]+$")

# Wufoo caps `pageSize` at 100 rows per request.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
VALIDATE_TIMEOUT_SECONDS = 10
MAX_RETRIES = 5


class WufooRetryableError(Exception):
    """Raised for transient API responses (429 / 5xx) so tenacity retries them."""


@dataclasses.dataclass
class WufooResumeConfig:
    # Row offset (Wufoo `pageStart`) of the next page to fetch. Limit/offset pagination is
    # deterministic, so a crashed full-refresh sync resumes from the offset after the last page
    # yielded; merge dedupes any re-pulled rows on the primary key.
    page_start: int = 0


def base_url(subdomain: str) -> str:
    return f"https://{subdomain}.wufoo.com/api/v3"


def _basic_token(api_key: str) -> str:
    # Wufoo uses HTTP Basic auth with the API key as the username and any non-empty string as the
    # password — the password value is ignored by Wufoo but must be present.
    return base64.b64encode(f"{api_key}:footastic".encode("ascii")).decode("ascii")


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Basic {_basic_token(api_key)}", "Accept": "application/json"}


def _redact_values(api_key: str) -> tuple[str, ...]:
    # Mask both the raw key and the derived Basic token so neither leaks into logged URLs/samples.
    return (api_key, _basic_token(api_key))


@retry(
    retry=retry_if_exception_type((WufooRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    page_start: int,
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.get(
        url,
        params={"pageStart": page_start, "pageSize": PAGE_SIZE},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise WufooRetryableError(f"Wufoo API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Wufoo API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def get_rows(
    api_key: str,
    subdomain: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[WufooResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = WUFOO_ENDPOINTS[endpoint]
    # One session reused across pages so urllib3 keeps the connection alive. Redirects are pinned
    # off so the user-supplied credential can't be replayed to a cross-host redirect target
    # (SSRF / credential-exfiltration defense-in-depth). urllib3 retries are disabled so tenacity
    # (on `_fetch_page`) is the single retry layer.
    session = make_tracked_session(
        headers=_headers(api_key),
        redact_values=_redact_values(api_key),
        allow_redirects=False,
        retry=Retry(total=0),
    )
    url = f"{base_url(subdomain)}/{config.path}"

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page_start = resume.page_start if resume else 0
    if resume and resume.page_start > 0:
        logger.debug(f"Wufoo: resuming {endpoint} from pageStart {page_start}")

    while True:
        data = _fetch_page(session, url, page_start, logger)

        items = data.get(config.data_key) or []
        if not isinstance(items, list):
            items = []
        if items:
            yield items

        # A short (or empty) page means the account has no further rows for this endpoint.
        if len(items) < PAGE_SIZE:
            break

        page_start += PAGE_SIZE
        # Save state AFTER yielding so a crash re-fetches the page we just emitted rather than
        # skipping it — merge dedupes the re-yielded rows on the primary key.
        resumable_source_manager.save_state(WufooResumeConfig(page_start=page_start))


def wufoo_source(
    api_key: str,
    subdomain: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[WufooResumeConfig],
) -> SourceResponse:
    config = WUFOO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            subdomain=subdomain,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def validate_credentials(api_key: str, subdomain: str) -> Optional[int]:
    """Probe a cheap list endpoint. Returns the HTTP status code, or ``None`` on a connection error."""
    if not SUBDOMAIN_REGEX.match(subdomain):
        return None
    url = f"{base_url(subdomain)}/forms.json"
    try:
        response = make_tracked_session(
            headers=_headers(api_key),
            redact_values=_redact_values(api_key),
            allow_redirects=False,
            retry=Retry(total=0),
        ).get(url, params={"pageSize": 1}, timeout=VALIDATE_TIMEOUT_SECONDS)
    except Exception:
        return None

    return response.status_code
