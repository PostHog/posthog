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
from products.warehouse_sources.backend.temporal.data_imports.sources.mux.settings import (
    MUX_ENDPOINTS,
    MuxEndpointConfig,
)

MUX_BASE_URL = "https://api.mux.com"
# Endpoint used to confirm a token is genuine when no specific schema is being validated.
DEFAULT_VALIDATION_PATH = "/video/v1/assets"


class MuxRetryableError(Exception):
    pass


@dataclasses.dataclass
class MuxResumeConfig:
    # Next offset page to fetch (offset/limit pagination). None for cursor-paginated endpoints.
    page: int | None = None
    # Next `next_cursor` value to fetch (cursor pagination, List Assets only).
    cursor: str | None = None


def _make_session(access_token_id: str, secret_key: str) -> requests.Session:
    # Mux authenticates with HTTP Basic auth (Access Token ID as username, Secret as password).
    # Redact the secret wherever it might surface in tracked logs/samples.
    session = make_tracked_session(redact_values=(secret_key,))
    session.auth = (access_token_id, secret_key)
    return session


@retry(
    retry=retry_if_exception_type((MuxRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict:
    response = session.get(url, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise MuxRetryableError(f"Mux API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Mux API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def get_validation_status(access_token_id: str, secret_key: str, path: str) -> int | None:
    """Probe a list endpoint and return the HTTP status code, or None on a transport error."""
    url = f"{MUX_BASE_URL}{path}?{urlencode({'limit': 1})}"
    try:
        session = _make_session(access_token_id, secret_key)
        return session.get(url, timeout=10).status_code
    except Exception:
        return None


def _strip_sensitive_fields(item: dict[str, Any], config: MuxEndpointConfig) -> dict[str, Any]:
    """Drop credential-bearing fields before the row is batched into the warehouse.

    Mux list responses embed live-stream ingest keys (`stream_key`) and direct-upload PUT URLs
    (`url`). Persisting them would expose a valid broadcast/upload credential to anyone who can
    query the imported table, crossing from analytics-read to write access in the customer's Mux
    account, so we remove them rather than import them. Live-stream simulcast targets carry their
    own per-destination `stream_key`, so those are stripped too.
    """
    if not config.sensitive_fields:
        return item
    cleaned = {k: v for k, v in item.items() if k not in config.sensitive_fields}
    targets = cleaned.get("simulcast_targets")
    if isinstance(targets, list):
        cleaned["simulcast_targets"] = [
            {k: v for k, v in target.items() if k != "stream_key"} if isinstance(target, dict) else target
            for target in targets
        ]
    return cleaned


def _normalize_row(item: dict[str, Any], config: MuxEndpointConfig) -> dict[str, Any]:
    """Coerce the partition timestamp to an int so datetime partitioning can parse it.

    Mux returns `created_at` as a string-encoded Unix timestamp in seconds (e.g. "1609869152").
    The pipeline's datetime partitioner parses ints via `fromtimestamp` but would misparse the raw
    string, so convert it where it's the partition key.
    """
    if config.partition_key == "created_at":
        created_at = item.get("created_at")
        if isinstance(created_at, str) and created_at.isdigit():
            return {**item, "created_at": int(created_at)}
    return item


def get_rows(
    access_token_id: str,
    secret_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MuxResumeConfig],
) -> Iterator[Any]:
    config = MUX_ENDPOINTS[endpoint]
    session = _make_session(access_token_id, secret_key)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume and resume.page else 1
    cursor = resume.cursor if resume else None
    if resume is not None:
        logger.debug(f"Mux: resuming {endpoint} from page={page}, cursor={cursor}")

    while True:
        params: dict[str, Any] = {"limit": config.page_size}
        if config.use_cursor:
            if cursor:
                params["cursor"] = cursor
        else:
            params["page"] = page

        url = f"{MUX_BASE_URL}{config.path}?{urlencode(params)}"
        data = _fetch_page(session, url, logger)

        items = data.get("data") or []
        next_cursor = data.get("next_cursor") if config.use_cursor else None

        # A full offset page implies there may be another; a present `next_cursor` means more remain.
        if config.use_cursor:
            has_next = bool(next_cursor)
            next_state = MuxResumeConfig(cursor=next_cursor)
        else:
            has_next = len(items) >= config.page_size
            next_state = MuxResumeConfig(page=page + 1)

        for item in items:
            batcher.batch(_normalize_row(_strip_sensitive_fields(item, config), config))

            if batcher.should_yield():
                yield batcher.get_table()

        if not has_next or not items:
            break

        # Save state on the page boundary, once the whole page is batched/yielded, pointing at the
        # next page. The batcher can yield mid-page (its row threshold need not align with page_size),
        # so advancing the bookmark only at page boundaries means a crash re-fetches at most the
        # current page — merge dedupes the re-yielded rows — instead of skipping rows that were
        # batched but not yet yielded when a mid-page batch fired.
        resumable_source_manager.save_state(next_state)

        if config.use_cursor:
            cursor = next_cursor
        else:
            page += 1

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def mux_source(
    access_token_id: str,
    secret_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MuxResumeConfig],
) -> SourceResponse:
    config = MUX_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_token_id=access_token_id,
            secret_key=secret_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
