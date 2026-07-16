import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.alguna.settings import ALGUNA_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

ALGUNA_BASE_URL = "https://api.alguna.io"
# Alguna's API is date-versioned; every request must send this header or calls fail.
ALGUNA_API_VERSION = "2026-04-01"
PAGE_LIMIT = 100
REQUEST_TIMEOUT_SECONDS = 60


class AlgunaRetryableError(Exception):
    pass


@dataclasses.dataclass
class AlgunaResumeConfig:
    # Byte-for-byte deterministic restart point: list endpoints paginate with required
    # limit/offset params, so the row offset of the next unfetched page is the full resume state.
    offset: int = 0


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Alguna-Version": ALGUNA_API_VERSION,
        "Accept": "application/json",
    }


def _build_url(path: str, params: dict[str, Any]) -> str:
    return f"{ALGUNA_BASE_URL}{path}?{urlencode(params)}"


def validate_credentials(api_key: str) -> bool:
    url = _build_url("/customers", {"limit": 1, "offset": 0, "sort": "created_at:asc"})
    try:
        session = make_tracked_session(redact_values=(api_key,))
        response = session.get(url, headers=_get_headers(api_key), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


@retry(
    retry=retry_if_exception_type(
        (
            AlgunaRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise AlgunaRetryableError(f"Alguna API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Alguna API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AlgunaResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = ALGUNA_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    session = make_tracked_session(redact_values=(api_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume is not None else 0
    if offset:
        logger.debug(f"Alguna: resuming {endpoint} from offset={offset}")

    while True:
        params: dict[str, Any] = {"limit": PAGE_LIMIT, "offset": offset}
        if config.sort is not None:
            params["sort"] = config.sort

        data = _fetch_page(session, _build_url(config.path, params), headers, logger)
        # Direct access: a 200 body without "data" means the response shape changed — fail the
        # sync loudly instead of silently reporting 0 rows.
        items = data["data"]
        if not items:
            break

        yield items

        offset += len(items)
        # A short page means we've reached the end; don't save state for a finished sync.
        if len(items) < PAGE_LIMIT:
            break

        # Save AFTER yielding so a crash re-yields the last page rather than skipping it —
        # merge dedupes on the primary key.
        resumable_source_manager.save_state(AlgunaResumeConfig(offset=offset))


def alguna_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AlgunaResumeConfig],
) -> SourceResponse:
    config = ALGUNA_ENDPOINTS[endpoint]

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
