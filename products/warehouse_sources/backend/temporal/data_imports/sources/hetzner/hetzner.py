import random
import dataclasses
from collections.abc import Iterator
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.hetzner.settings import (
    HETZNER_ENDPOINTS,
    HetznerEndpointConfig,
)

# Single global base URL — Hetzner Cloud has no regional hosts.
HETZNER_BASE_URL = "https://api.hetzner.cloud/v1"

# Max page size the API accepts; anything larger is clamped by the server. Bigger pages mean fewer
# round trips against the 3600 req/hour budget.
PAGE_SIZE = 50

# Cap on how long we honor a rate-limit reset before retrying anyway, so a misreported reset header
# can't stall a worker past the activity heartbeat window.
MAX_RETRY_AFTER_SECONDS = 300.0


class HetznerRetryableError(Exception):
    """Raised for transient responses (429 / 5xx). Carries the server-advertised retry delay when
    the response provided one so the retry can wait exactly that long instead of guessing."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclasses.dataclass
class HetznerResumeConfig:
    # Page number to fetch first on resume. In-flight we checkpoint the CURRENT page after yielding a
    # batch: a crash re-fetches that one page rather than skipping its un-yielded tail (dropping rows
    # is worse than re-reading a page). On clean completion we advance the checkpoint PAST the last
    # page so a spurious retry resumes onto an empty page instead of replaying. These tables are full
    # refresh, so any rows a re-fetched page duplicates are bounded to that single page and are wiped
    # by the next non-resumed run, which overwrites the table from scratch.
    page: int = 1


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }


def _parse_retry_after(response: requests.Response) -> float | None:
    """Prefer the standard `Retry-After` (seconds); fall back to `RateLimit-Reset` (unix epoch
    seconds), which Hetzner returns on a throttled request. Returns None when neither is usable."""
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return float(retry_after)
        except ValueError:
            pass
    reset = response.headers.get("RateLimit-Reset")
    if reset:
        try:
            # Reset is an absolute epoch second; Date gives the server's "now" so we don't depend on
            # local clock skew. Fall back to a small delay if the delta is nonsensical.
            server_now = response.headers.get("Date")
            if server_now:
                now_ts = parsedate_to_datetime(server_now).timestamp()
                delta = float(reset) - now_ts
                return delta if delta > 0 else None
        except (ValueError, TypeError):
            pass
    return None


_backoff_wait = wait_exponential_jitter(initial=1, max=30)


def _retry_wait(state: RetryCallState) -> float:
    """Wait the server-advertised reset (capped, plus jitter) when we got one; otherwise exponential
    backoff. Jitter keeps sources sharing one project token from all waking at the same reset instant."""
    if state.outcome is not None and state.outcome.failed:
        exc = state.outcome.exception()
        if isinstance(exc, HetznerRetryableError) and exc.retry_after is not None:
            return min(exc.retry_after, MAX_RETRY_AFTER_SECONDS) + random.uniform(0, 1)
    return _backoff_wait(state)


@retry(
    retry=retry_if_exception_type(
        (
            HetznerRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            # A mid-stream break on a chunked body; transient, so a fresh GET re-fetches the page.
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=_retry_wait,
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=60)

    # 429 (rate limited) and 5xx are transient — retry, honoring the reset header on a 429.
    if response.status_code == 429 or response.status_code >= 500:
        raise HetznerRetryableError(
            f"Hetzner API error (retryable): status={response.status_code}, url={url}",
            retry_after=_parse_retry_after(response) if response.status_code == 429 else None,
        )

    if not response.ok:
        logger.error(f"Hetzner API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _build_url(config: HetznerEndpointConfig, page: int) -> str:
    params: dict[str, Any] = {"page": page, "per_page": PAGE_SIZE}
    if config.sort:
        params["sort"] = config.sort
    return f"{HETZNER_BASE_URL}{config.path}?{urlencode(params)}"


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    """One cheap authenticated probe to confirm the token is genuine. Hetzner project tokens grant
    read access to every resource in the project (a read-only token still reads all of them), so
    there is no per-endpoint scope to check — a valid token can sync any table."""
    url = f"{HETZNER_BASE_URL}/ssh_keys?per_page=1"
    try:
        # redact_values masks the token in logged URLs / captured samples; allow_redirects=False keeps
        # a redirect from ever replaying the Authorization header (or the token in a query param) to
        # another host. Mirrors the hardened transport other warehouse sources use.
        session = make_tracked_session(redact_values=(api_token,), allow_redirects=False)
        response = session.get(url, headers=_get_headers(api_token), timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid Hetzner Cloud API token"
    try:
        message = response.json().get("error", {}).get("message", response.text)
    except (ValueError, AttributeError):
        message = response.text
    return False, message


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HetznerResumeConfig],
) -> Iterator[Any]:
    config = HETZNER_ENDPOINTS[endpoint]
    headers = _get_headers(api_token)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    # redact_values keeps the token out of tracked telemetry/samples; allow_redirects=False stops a
    # redirect from ever forwarding the Authorization header to another host.
    session = make_tracked_session(redact_values=(api_token,), allow_redirects=False)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume is not None else 1
    if resume is not None:
        logger.debug(f"Hetzner: resuming {endpoint} from page {page}")

    last_page = page
    while True:
        data = _fetch_page(session, _build_url(config, page), headers, logger)
        items = data.get(config.response_key) or []
        if not items:
            break

        last_page = page
        next_page = data.get("meta", {}).get("pagination", {}).get("next_page")
        # Checkpoint the CURRENT page: on resume we re-fetch it rather than jumping to next_page and
        # dropping this page's un-yielded tail. A re-fetch can re-yield rows already written, but that
        # is bounded to one page and self-heals on the next full-refresh run.
        checkpoint_page = page

        for item in items:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                resumable_source_manager.save_state(HetznerResumeConfig(page=checkpoint_page))

        if not next_page:
            break
        page = next_page

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()

    # Every page is now written. Advance the checkpoint past the last page so a crash between this
    # final write and the activity completing resumes onto an empty page (a no-op) instead of
    # replaying already-written pages from the last in-flight checkpoint and appending duplicates.
    resumable_source_manager.save_state(HetznerResumeConfig(page=last_page + 1))


def hetzner_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HetznerResumeConfig],
) -> SourceResponse:
    endpoint_config = HETZNER_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=endpoint_config.primary_keys,
        # id:asc (or default order for the catalog endpoints) — rows arrive oldest-id first.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
