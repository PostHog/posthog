import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from requests.exceptions import ChunkedEncodingError
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.settings import MAILERLITE_ENDPOINTS

MAILERLITE_BASE_URL = "https://connect.mailerlite.com/api"

# MailerLite caps list endpoints at 100 rows per page; default is 25.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60


class MailerLiteRetryableError(Exception):
    pass


@dataclasses.dataclass
class MailerLiteResumeConfig:
    # Absolute next-page URL returned by the API (carries the cursor / page number and limit).
    next_url: str


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _build_initial_url(path: str) -> str:
    return f"{MAILERLITE_BASE_URL}{path}?{urlencode({'limit': PAGE_SIZE})}"


def validate_credentials(api_key: str, path: str = "/subscribers") -> bool:
    """Confirm the API key is genuine with one cheap probe against a list endpoint."""
    url = f"{MAILERLITE_BASE_URL}{path}?{urlencode({'limit': 1})}"
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MailerLiteResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = MAILERLITE_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        url = resume_config.next_url
        # Guard the persisted resume URL too — only ever saved from a host-pinned `links.next`,
        # but re-check so a tampered Redis state can't redirect our authenticated request (SSRF).
        if not url.startswith(MAILERLITE_BASE_URL):
            raise ValueError(f"MailerLite resume state contains an unexpected URL: {url!r}")
        logger.debug(f"MailerLite: resuming {endpoint} from URL: {url}")
    else:
        url = _build_initial_url(config.path)

    @retry(
        # ChunkedEncodingError is a transient mid-stream connection drop while reading the
        # response body (e.g. "Connection broken: InvalidChunkLength"). It subclasses
        # RequestException directly, not ConnectionError, so it must be listed explicitly to be
        # retried rather than failing the whole import on a single dropped connection.
        retry=retry_if_exception_type(
            (MailerLiteRetryableError, requests.ReadTimeout, requests.ConnectionError, ChunkedEncodingError)
        ),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        response = make_tracked_session().get(page_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise MailerLiteRetryableError(
                f"MailerLite API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"MailerLite API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(url)

        items = data.get("data", [])
        if items:
            yield items

        # Both cursor (subscribers) and page-number (everything else) pagination return an
        # absolute next-page URL in `links.next`, or `None` on the last page.
        next_url = data.get("links", {}).get("next")
        if not next_url:
            break

        # Only follow pagination URLs that stay on the canonical MailerLite host, so a tampered or
        # compromised API response can't point our authenticated request at an internal address
        # (SSRF) and leak the API key carried in the Authorization header.
        if not isinstance(next_url, str) or not next_url.startswith(MAILERLITE_BASE_URL):
            logger.warning(f"MailerLite: ignoring off-host pagination URL: {next_url!r}")
            break

        # Save state only after yielding the current page, so a crash re-yields the last page
        # (merge dedupes on primary key) instead of skipping it.
        resumable_source_manager.save_state(MailerLiteResumeConfig(next_url=next_url))
        url = next_url


def mailerlite_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MailerLiteResumeConfig],
) -> SourceResponse:
    endpoint_config = MAILERLITE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
