import time
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.decagon.settings import DECAGON_ENDPOINTS

DECAGON_BASE_URL = "https://api.decagon.ai"

REQUEST_TIMEOUT_SECONDS = 60

# Decagon enforces a hard limit of 1 request/second across all API endpoints and
# automatically IP-bans gross violators, so requests are spaced client-side rather
# than relying on 429 backoff alone.
MIN_SECONDS_BETWEEN_REQUESTS = 1.0


class DecagonRetryableError(Exception):
    pass


@dataclasses.dataclass
class DecagonResumeConfig:
    # The next-page export cursor returned by Decagon (`next_page_cursor`).
    cursor: str


class RequestThrottle:
    """Spaces consecutive requests at least `min_interval` seconds apart."""

    def __init__(self, min_interval: float = MIN_SECONDS_BETWEEN_REQUESTS) -> None:
        self._min_interval = min_interval
        self._last_request_at: Optional[float] = None

    def wait(self) -> None:
        if self._last_request_at is not None:
            remaining = self._min_interval - (time.monotonic() - self._last_request_at)
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at = time.monotonic()


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def validate_credentials(api_key: str) -> bool:
    """Probe the export endpoint (the only one this source calls) to confirm the key works."""
    try:
        response = make_tracked_session().get(
            f"{DECAGON_BASE_URL}/conversation/export",
            headers=_get_headers(api_key),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DecagonResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = DECAGON_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    url = f"{DECAGON_BASE_URL}{config.path}"
    session = make_tracked_session()
    throttle = RequestThrottle()

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor: Optional[str] = resume_config.cursor if resume_config else None
    if cursor:
        logger.debug(f"Decagon: resuming {endpoint} from saved cursor")

    @retry(
        retry=retry_if_exception_type((DecagonRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        # The 1 rps limit means a 429 needs a generous backoff, not a quick retry.
        wait=wait_exponential_jitter(initial=2, max=60),
        reraise=True,
    )
    def fetch_page(params: dict[str, str]) -> dict[str, Any]:
        throttle.wait()
        response = session.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise DecagonRetryableError(f"Decagon API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Decagon API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    # A conversation that receives new messages re-enters the export stream on a later
    # page, so a single walk can emit the same conversation twice. Full-refresh writes
    # are plain appends (no primary-key merge), so re-emissions are skipped client-side;
    # the next sync picks up the newer version.
    seen_ids: set[str] = set()

    while True:
        # An omitted cursor starts the stream at the oldest conversations.
        params = {"cursor": cursor} if cursor else {}
        data = fetch_page(params)

        items = data.get(config.data_key) or []
        next_cursor = data.get("next_page_cursor")

        fresh: list[dict[str, Any]] = []
        for item in items:
            item_id = item.get("conversation_id")
            if item_id is not None:
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
            fresh.append(item)

        if fresh:
            yield fresh
            # Save state only after yielding, so a crash re-yields the last batch rather
            # than skipping it (the duplicate rows a resumed re-yield can produce are
            # bounded to one page and cleaned up by the next full refresh).
            if next_cursor:
                resumable_source_manager.save_state(DecagonResumeConfig(cursor=str(next_cursor)))

        # `next_page_cursor` is null once the stream is exhausted. Also stop if the
        # server ever returns the cursor we just used, to guard against spinning on
        # one page forever.
        if not next_cursor or str(next_cursor) == cursor:
            break

        cursor = str(next_cursor)


def decagon_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DecagonResumeConfig],
) -> SourceResponse:
    config = DECAGON_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
    )
