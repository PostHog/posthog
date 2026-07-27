import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.segment.settings import (
    REGION_BASE_URLS,
    SEGMENT_ENDPOINTS,
    SegmentEndpointConfig,
)

# Segment's Public API caps a page at 1000 items (default 200). We request the max to minimize the
# number of round-trips while staying within documented limits and well clear of the lower per-endpoint
# rate caps (some endpoints are throttled to 250 req/min).
PAGE_SIZE = 200


class SegmentRetryableError(Exception):
    pass


@dataclasses.dataclass
class SegmentResumeConfig:
    # Opaque base64 cursor (`data.pagination.next`) for the next page of the endpoint being synced.
    cursor: str


def _base_url(region: str) -> str:
    return REGION_BASE_URLS.get(region, REGION_BASE_URLS["api"])


def _headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }


def _build_url(base_url: str, path: str, cursor: str | None) -> str:
    """Build a list URL with Segment's pagination query params.

    Segment uses bracketed keys (`pagination[count]`, `pagination[cursor]`). The keys are constructed
    internally so they're left literal; only the opaque cursor value (base64, contains `=`) is encoded.
    """
    params = [f"pagination[count]={PAGE_SIZE}"]
    if cursor:
        params.append(f"pagination[cursor]={quote(cursor, safe='')}")
    return f"{base_url}{path}?{'&'.join(params)}"


@retry(
    retry=retry_if_exception_type((SegmentRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> dict:
    response = session.get(url, headers=headers, timeout=60)

    # 429 (rate limit) and 5xx are transient; back off and retry.
    if response.status_code == 429 or response.status_code >= 500:
        raise SegmentRetryableError(f"Segment API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Segment API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _extract_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the resource array out of a Segment list response.

    The body is `{"data": {"<resource>": [...], "pagination": {...}}}`. The resource key varies and
    doesn't always match the endpoint name (e.g. `/audit-events` returns `events`, `/labels` returns
    `labels`), so we take the single list-valued entry under `data` rather than hardcoding the key.
    """
    payload = data.get("data", {})
    if not isinstance(payload, dict):
        return []
    for key, value in payload.items():
        if key == "pagination":
            continue
        if isinstance(value, list):
            return value
    return []


def _redact_rows(rows: list[dict[str, Any]], redacted_fields: frozenset[str]) -> list[dict[str, Any]]:
    """Drop credential-like top-level fields (e.g. destination `settings`, source `writeKeys`) so
    they never land in a queryable warehouse table. See `SegmentEndpointConfig.redacted_fields`.
    """
    if not redacted_fields:
        return rows
    return [
        {key: value for key, value in row.items() if key not in redacted_fields} if isinstance(row, dict) else row
        for row in rows
    ]


def _next_cursor(data: dict[str, Any]) -> str | None:
    payload = data.get("data", {})
    pagination = payload.get("pagination", {}) if isinstance(payload, dict) else {}
    next_cursor = pagination.get("next") if isinstance(pagination, dict) else None
    return next_cursor or None


def get_rows(
    api_token: str,
    region: str,
    config: SegmentEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SegmentResumeConfig],
) -> Iterator[Any]:
    base_url = _base_url(region)
    headers = _headers(api_token)
    # One session reused across pages so urllib3 keeps the connection alive instead of re-handshaking.
    # `redact_values` masks the bearer token in tracked request logs and captured HTTP samples.
    session = make_tracked_session(redact_values=(api_token,))

    # `GET /` (Get Workspace) returns a single object, not a paginated list.
    if config.single_object_key is not None:
        data = _fetch(session, f"{base_url}{config.path}", headers, logger)
        obj = data.get("data", {}).get(config.single_object_key)
        if obj:
            yield _redact_rows([obj], config.redacted_fields)
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume.cursor if resume else None
    if cursor:
        logger.debug(f"Segment: resuming {config.name} from cursor={cursor}")

    while True:
        url = _build_url(base_url, config.path, cursor)
        data = _fetch(session, url, headers, logger)

        rows = _extract_rows(data)
        if rows:
            yield _redact_rows(rows, config.redacted_fields)

        cursor = _next_cursor(data)
        if not cursor:
            break

        # Save AFTER yielding so a crash re-yields the last page (merge dedupes on the primary key)
        # rather than skipping it.
        resumable_source_manager.save_state(SegmentResumeConfig(cursor=cursor))


def segment_source(
    api_token: str,
    region: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SegmentResumeConfig],
) -> SourceResponse:
    config = SEGMENT_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            region=region,
            config=config,
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


def validate_credentials(api_token: str, region: str) -> bool:
    """Cheapest probe that a token is genuine: Get Workspace (`GET /`) for the token's region."""
    try:
        response = make_tracked_session(redact_values=(api_token,)).get(
            f"{_base_url(region)}/",
            headers=_headers(api_token),
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False
