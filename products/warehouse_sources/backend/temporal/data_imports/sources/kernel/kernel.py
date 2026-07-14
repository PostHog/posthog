import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.kernel.settings import (
    KERNEL_ENDPOINTS,
    KernelEndpointConfig,
)

KERNEL_BASE_URL = "https://api.onkernel.com"

# Kernel caps list page size at 100 (1-100, default 20).
PAGE_SIZE = 100


class KernelRetryableError(Exception):
    pass


@dataclasses.dataclass
class KernelResumeConfig:
    # Next offset to request. Offset pagination means resuming is just "start from this offset";
    # merge/full-refresh dedupe on the primary key handles any page re-fetched after a crash.
    offset: int = 0


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _build_url(path: str, params: dict[str, Any]) -> str:
    query = urlencode(params)
    return f"{KERNEL_BASE_URL}{path}?{query}" if query else f"{KERNEL_BASE_URL}{path}"


def _extract_items(body: Any) -> list[dict[str, Any]]:
    """Pull the row list out of a Kernel list response.

    Kernel signals pagination through headers (X-Has-More / X-Next-Offset), so the body is
    expected to be a bare JSON array. We defensively also accept the common wrapped shapes
    ({"data": [...]} etc.) since this has not been verified against a live API.
    """
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("data", "items", "results", "records"):
            value = body.get(key)
            if isinstance(value, list):
                return value
    return []


def _next_page(headers: Any, current_offset: int, page_len: int) -> tuple[bool, int]:
    """Return (has_more, next_offset) from the response headers, falling back to offset math."""
    has_more_header = str(headers.get("X-Has-More", "")).strip().lower()
    if has_more_header in ("true", "false"):
        has_more = has_more_header == "true"
    else:
        # No header: assume more pages only while a full page came back.
        has_more = page_len >= PAGE_SIZE

    next_offset_header = headers.get("X-Next-Offset")
    if next_offset_header is not None:
        try:
            return has_more, int(next_offset_header)
        except (TypeError, ValueError):
            pass
    return has_more, current_offset + page_len


@retry(
    retry=retry_if_exception_type(
        (
            KernelRetryableError,
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
) -> requests.Response:
    response = session.get(url, headers=headers, timeout=60)

    # Kernel returns 429 with a Retry-After per-organization rate limit; honor it via retry backoff.
    if response.status_code == 429 or response.status_code >= 500:
        raise KernelRetryableError(f"Kernel API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Kernel API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    """Probe a cheap list endpoint. Returns (ok, status_code); status is None on transport failure."""
    url = _build_url("/apps", {"limit": 1})
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10)
    except Exception:
        return False, None
    return response.status_code == 200, response.status_code


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[KernelResumeConfig],
) -> Iterator[Any]:
    config = KERNEL_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    # One session reused across every page so urllib3 keeps the connection alive.
    session = make_tracked_session()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume is not None else 0
    if resume is not None:
        logger.debug(f"Kernel: resuming {endpoint} from offset={offset}")

    while True:
        params: dict[str, Any] = {"limit": PAGE_SIZE, "offset": offset, **config.extra_params}
        url = _build_url(config.path, params)
        response = _fetch_page(session, url, headers, logger)
        items = _extract_items(response.json())

        if not items:
            break

        for item in items:
            batcher.batch(item)

        has_more, next_offset = _next_page(response.headers, offset, len(items))

        if batcher.should_yield():
            yield batcher.get_table()
            # Save AFTER yielding (and only when more pages remain) so a crash re-fetches the
            # last window rather than skipping it.
            if has_more:
                resumable_source_manager.save_state(KernelResumeConfig(offset=next_offset))

        if not has_more:
            break

        offset = next_offset

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def kernel_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[KernelResumeConfig],
) -> SourceResponse:
    endpoint_config: KernelEndpointConfig = KERNEL_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Full refresh for every endpoint (see settings.py) - no incremental watermark to order,
        # so the default ascending sort_mode is fine. Partitioning is left to the pipeline's
        # auto-detection (falls back to created_at when present); revisit once the live schema is
        # confirmed and a stable partition key per endpoint can be verified.
        sort_mode="asc",
    )
