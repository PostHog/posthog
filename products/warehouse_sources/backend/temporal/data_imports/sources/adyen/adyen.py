import re
import csv
import codecs
import dataclasses
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.adyen.settings import (
    ADYEN_ENDPOINTS,
    AdyenApi,
    AdyenEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

ADYEN_ENVIRONMENTS = ("test", "live")
DEFAULT_ENVIRONMENT = "live"

# Adyen serves each read API from its own host, with the environment baked into the hostname.
# Fixed allow-list, so a customer-supplied environment can never retarget the API key.
ADYEN_HOSTS: dict[str, dict[str, str]] = {
    "test": {
        "transfers": "https://balanceplatform-api-test.adyen.com/btl/v4",
        "configuration": "https://balanceplatform-api-test.adyen.com/bcl/v2",
        "management": "https://management-test.adyen.com/v3",
        "reports": "https://ca-test.adyen.com",
    },
    "live": {
        "transfers": "https://balanceplatform-api-live.adyen.com/btl/v4",
        "configuration": "https://balanceplatform-api-live.adyen.com/bcl/v2",
        "management": "https://management-live.adyen.com/v3",
        "reports": "https://ca-live.adyen.com",
    },
}

PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 120
REPORT_TIMEOUT_SECONDS = 600
# The Transfers API rejects a createdUntil more than 6 months after createdSince, so long
# backfills are walked in windows well inside that limit.
MAX_WINDOW_DAYS = 150
# How far back the first (non-incremental) sync reaches when no start date is configured.
DEFAULT_BACKFILL_DAYS = 365
# Report batch numbers are sequential per merchant account, but a batch can be missing (no
# settlement that period, or a report aged out), so tolerate a short run of gaps before stopping.
MAX_CONSECUTIVE_MISSING_BATCHES = 3
# Hard cap on report files fetched in one sync — the next run resumes at the watermark.
MAX_BATCHES_PER_SYNC = 500
# Report files can be large; yield them in chunks rather than one list per file.
REPORT_CHUNK_SIZE = 5000

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


class AdyenConfigurationError(Exception):
    """The stored config can't satisfy the requested endpoint (missing or malformed identifier)."""


@dataclasses.dataclass
class AdyenResumeConfig:
    """Checkpoint for whichever pagination style the running endpoint uses.

    One dataclass covers every endpoint because a job only ever syncs one schema, so the
    unused fields simply stay `None`.
    """

    # Transfers API: the window being walked plus the opaque page cursor within it.
    window_start: str | None = None
    cursor: str | None = None
    # Configuration API offset pagination, and the parent index for fan-out children.
    offset: int | None = None
    parent_index: int | None = None
    # Management API page pagination.
    page_number: int | None = None
    # Report downloads: the last batch number successfully yielded.
    batch_number: int | None = None


def resolve_environment(environment: Optional[str]) -> str:
    if environment is not None and environment in ADYEN_ENVIRONMENTS:
        return environment
    return DEFAULT_ENVIRONMENT


def base_url(environment: Optional[str], api: AdyenApi) -> str:
    return ADYEN_HOSTS[resolve_environment(environment)][api]


def _require_identifier(value: Optional[str], label: str) -> str:
    """Return a config identifier that is safe to interpolate into a request path."""
    cleaned = (value or "").strip()
    if not cleaned:
        raise AdyenConfigurationError(f"{label} is required to sync this table.")
    if not _IDENTIFIER_RE.match(cleaned):
        raise AdyenConfigurationError(f"{label} contains unsupported characters.")
    return cleaned


def _get_session(api_key: str) -> requests.Session:
    return make_tracked_session(
        headers={"X-API-Key": api_key, "Accept": "application/json"},
        redact_values=(api_key,),
        # `requests` replays custom headers (including `X-API-Key`) across a cross-host 3xx, so
        # pin redirects off to keep the credential on the host it was issued for.
        allow_redirects=False,
        # Report and transfer bodies carry transaction identifiers, amounts and free-form
        # references the name-based scrubbers can't recognise — keep them out of sample capture.
        capture=False,
    )


def _format_timestamp(value: datetime) -> str:
    dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_datetime(value: Any) -> datetime | None:
    """Coerce a stored incremental watermark (datetime, date or ISO string) into UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _to_batch_number(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _resolve_start(
    start_date: Optional[str],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    now: datetime,
) -> datetime:
    if should_use_incremental_field:
        watermark = _to_datetime(db_incremental_field_last_value)
        if watermark is not None:
            return watermark

    configured = _to_datetime(start_date) if start_date else None
    if configured is not None:
        return configured

    return now - timedelta(days=DEFAULT_BACKFILL_DAYS)


def iter_windows(start: datetime, end: datetime) -> Iterator[tuple[datetime, datetime]]:
    """Split [start, end] into ascending chunks the Transfers API will accept."""
    if end <= start:
        return
    window_start = start
    while window_start < end:
        window_end = min(window_start + timedelta(days=MAX_WINDOW_DAYS), end)
        yield window_start, window_end
        window_start = window_end


def next_cursor(payload: Any) -> str | None:
    """Pull the opaque cursor out of `_links.next`.

    Only the cursor is kept — the next page is rebuilt against our own host, so a tampered
    response can't point the authenticated request at another server.
    """
    if not isinstance(payload, dict):
        return None
    links = payload.get("_links")
    if not isinstance(links, dict):
        return None
    next_link = links.get("next")
    if not isinstance(next_link, dict):
        return None
    href = next_link.get("href")
    if not isinstance(href, str) or not href:
        return None
    values = parse_qs(urlparse(href).query).get("cursor")
    return values[0] if values else None


def extract_items(payload: Any, data_key: Optional[str]) -> list[dict[str, Any]]:
    if data_key is None:
        return payload if isinstance(payload, list) else []
    if not isinstance(payload, dict):
        return []
    items = payload.get(data_key, [])
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def normalize_header(header: str) -> str:
    """`Gross Debit (GC)` becomes the stable column `gross_debit_gc`."""
    return re.sub(r"[^0-9a-zA-Z]+", "_", header).strip("_").lower()


def parse_report_rows(
    lines: Iterable[str], batch_number: int, logger: FilteringBoundLogger
) -> Iterator[dict[str, Any]]:
    # `lines` is any iterator of physical CSV lines (a live response stream or a StringIO), so a
    # large report is parsed row-by-row without buffering the whole file.
    reader = csv.reader(lines)
    headers: list[str] | None = None
    for row in reader:
        if headers is None:
            headers = [normalize_header(header) for header in row]
            continue
        if not any(cell.strip() for cell in row):
            continue
        # zip would silently truncate a short row and drop primary-key columns, corrupting
        # dedupe — skip the malformed line instead so the failure is visible.
        if len(row) != len(headers):
            logger.warning(
                "Adyen settlement report row length mismatch; skipping row",
                expected=len(headers),
                got=len(row),
                batch_number=batch_number,
            )
            continue
        parsed: dict[str, Any] = dict(zip(headers, row))
        # The report's own `Batch Number` column is a string; the requested batch is the
        # authoritative integer watermark, so it always wins.
        parsed["batch_number"] = batch_number
        yield parsed


def _request(
    session: requests.Session,
    url: str,
    logger: FilteringBoundLogger,
    headers: Optional[dict[str, str]] = None,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
) -> requests.Response:
    """One GET through the tracked session, which already retries 429/5xx honoring Retry-After."""
    response = session.get(url, headers=headers, timeout=timeout)
    if not response.ok:
        logger.error(f"Adyen API error: status={response.status_code}, url={url}")
        response.raise_for_status()
    return response


def _build_url(host: str, path: str, params: dict[str, Any]) -> str:
    if not params:
        return f"{host}{path}"
    return f"{host}{path}?{urlencode(params)}"


def validate_credentials(
    environment: Optional[str],
    api_key: str,
    balance_platform: Optional[str] = None,
    merchant_account: Optional[str] = None,
) -> tuple[bool, str | None]:
    """Probe the API key with one cheap call, without touching customer data.

    `GET /me` returns the calling credential's own details. A 403 means the key is genuine but
    lacks the Management API role — legitimate for a report-only credential, so it passes. A key
    issued in a Balance Platform Customer Area may not be known to the Management API at all, so
    a 401 there falls back to probing the balance platform the key was issued for.
    """
    for value, label in ((balance_platform, "Balance platform ID"), (merchant_account, "Merchant account")):
        if value and not _IDENTIFIER_RE.match(value.strip()):
            return False, f"{label} contains unsupported characters."

    session = _get_session(api_key)
    try:
        status = session.get(f"{base_url(environment, 'management')}/me", timeout=30).status_code
        if status == 401 and balance_platform:
            platform = balance_platform.strip()
            status = session.get(
                f"{base_url(environment, 'configuration')}/balancePlatforms/{platform}", timeout=30
            ).status_code
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if status in (200, 403):
        return True, None
    if status == 401:
        return False, "Adyen rejected the API key. Check the key and that it matches the selected environment."
    return False, f"Adyen credential validation failed (status {status})."


def _iter_cursor_pages(
    session: requests.Session,
    config: AdyenEndpointConfig,
    host: str,
    balance_platform: str,
    start: datetime,
    end: datetime,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[AdyenResumeConfig],
    resume: Optional[AdyenResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume_window = _to_datetime(resume.window_start) if resume is not None else None
    cursor = resume.cursor if resume is not None else None

    for window_start, window_end in iter_windows(start, end):
        # Skip windows already walked to completion before the interruption.
        if resume_window is not None and window_start < resume_window:
            continue
        page_cursor = cursor if resume_window is not None and window_start == resume_window else None
        resume_window = None

        while True:
            params: dict[str, Any] = {
                "balancePlatform": balance_platform,
                "createdSince": _format_timestamp(window_start),
                "createdUntil": _format_timestamp(window_end),
                "limit": PAGE_SIZE,
                "sortOrder": "asc",
            }
            if page_cursor:
                params["cursor"] = page_cursor

            payload = _request(session, _build_url(host, config.path, params), logger).json()
            items = extract_items(payload, config.data_key)
            if items:
                yield items

            page_cursor = next_cursor(payload)
            if not page_cursor:
                break

            # Checkpoint after yielding, so a crash re-yields the last batch (merge dedupes on
            # the primary key) instead of skipping it.
            manager.save_state(
                AdyenResumeConfig(window_start=_format_timestamp(window_start), cursor=page_cursor),
            )


def _iter_offset_pages(
    session: requests.Session,
    host: str,
    path: str,
    data_key: Optional[str],
    logger: FilteringBoundLogger,
    start_offset: int = 0,
    on_page: Callable[[int], None] | None = None,
) -> Iterator[list[dict[str, Any]]]:
    offset = start_offset
    while True:
        payload = _request(session, _build_url(host, path, {"limit": PAGE_SIZE, "offset": offset}), logger).json()
        items = extract_items(payload, data_key)
        if not items:
            return

        yield items

        if len(items) < PAGE_SIZE:
            return

        offset += PAGE_SIZE
        if on_page is not None:
            on_page(offset)


def _iter_page_number_pages(
    session: requests.Session,
    host: str,
    path: str,
    data_key: Optional[str],
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[AdyenResumeConfig],
    start_page: int = 1,
) -> Iterator[list[dict[str, Any]]]:
    page_number = start_page
    while True:
        params = {"pageSize": PAGE_SIZE, "pageNumber": page_number}
        payload = _request(session, _build_url(host, path, params), logger).json()
        items = extract_items(payload, data_key)
        if not items:
            return

        yield items

        pages_total = payload.get("pagesTotal") if isinstance(payload, dict) else None
        if len(items) < PAGE_SIZE or (isinstance(pages_total, int) and page_number >= pages_total):
            return

        page_number += 1
        manager.save_state(AdyenResumeConfig(page_number=page_number))


def _iter_fanout_pages(
    session: requests.Session,
    config: AdyenEndpointConfig,
    host: str,
    balance_platform: str,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[AdyenResumeConfig],
    start_parent_index: int,
) -> Iterator[list[dict[str, Any]]]:
    parent = ADYEN_ENDPOINTS[config.parent] if config.parent else None
    if parent is None:
        raise AdyenConfigurationError(f"Adyen endpoint {config.name} has no parent endpoint configured.")

    parent_path = parent.path.format(balance_platform=balance_platform)
    parent_ids: list[str] = []
    for page in _iter_offset_pages(session, host, parent_path, parent.data_key, logger):
        parent_ids.extend(str(item["id"]) for item in page if item.get("id"))

    for index, parent_id in enumerate(parent_ids):
        if index < start_parent_index:
            continue
        child_path = config.path.format(parent_id=parent_id)
        for page in _iter_offset_pages(session, host, child_path, config.data_key, logger):
            yield page
        manager.save_state(AdyenResumeConfig(parent_index=index + 1))


def _iter_report_batches(
    session: requests.Session,
    config: AdyenEndpointConfig,
    host: str,
    merchant_account: str,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[AdyenResumeConfig],
    start_batch: int,
) -> Iterator[list[dict[str, Any]]]:
    batch_number = max(start_batch, 1)
    last_batch = batch_number + MAX_BATCHES_PER_SYNC
    consecutive_misses = 0

    while batch_number < last_batch:
        file_name = config.path.format(batch_number=batch_number)
        url = f"{host}/reports/download/MerchantAccount/{merchant_account}/{file_name}"
        # `stream=True` so a large settlement report is parsed incrementally instead of buffered
        # whole in the worker (a report file can be very large for a high-volume merchant).
        response = session.get(
            url,
            # Adyen only compresses the download when the client advertises gzip.
            headers={"Accept": "text/csv", "Accept-Encoding": "gzip"},
            timeout=REPORT_TIMEOUT_SECONDS,
            stream=True,
        )

        if response.status_code == 404:
            response.close()
            consecutive_misses += 1
            if consecutive_misses > MAX_CONSECUTIVE_MISSING_BATCHES:
                logger.debug(f"Adyen: no settlement report at batch {batch_number}, stopping")
                return
            batch_number += 1
            continue

        if not response.ok:
            logger.error(f"Adyen report download error: status={response.status_code}, url={url}")
            response.close()
            response.raise_for_status()

        consecutive_misses = 0
        chunk: list[dict[str, Any]] = []
        try:
            # Decode gzip on the fly and read physical lines off the socket so quoted multi-line
            # CSV fields survive (unlike `iter_lines`, which strips the terminators csv needs).
            response.raw.decode_content = True
            lines = codecs.getreader("utf-8")(response.raw)
            for row in parse_report_rows(lines, batch_number, logger):
                chunk.append(row)
                if len(chunk) >= REPORT_CHUNK_SIZE:
                    yield chunk
                    chunk = []
            if chunk:
                yield chunk
        finally:
            response.close()

        manager.save_state(AdyenResumeConfig(batch_number=batch_number))
        batch_number += 1


def get_rows(
    environment: Optional[str],
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AdyenResumeConfig],
    balance_platform: Optional[str] = None,
    merchant_account: Optional[str] = None,
    start_date: Optional[str] = None,
    settlement_report_start_batch: Optional[int] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = ADYEN_ENDPOINTS[endpoint]
    host = base_url(environment, config.api)
    session = _get_session(api_key)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.pagination == "report_batch":
        account = _require_identifier(merchant_account, "Merchant account")
        watermark = _to_batch_number(db_incremental_field_last_value) if should_use_incremental_field else None
        if resume is not None and resume.batch_number is not None:
            start_batch = resume.batch_number + 1
        elif watermark is not None:
            start_batch = watermark + 1
        else:
            start_batch = settlement_report_start_batch or 1
        yield from _iter_report_batches(session, config, host, account, logger, resumable_source_manager, start_batch)
        return

    if config.pagination == "cursor":
        platform = _require_identifier(balance_platform, "Balance platform ID")
        now = datetime.now(UTC)
        start = _resolve_start(start_date, should_use_incremental_field, db_incremental_field_last_value, now)
        yield from _iter_cursor_pages(
            session, config, host, platform, start, now, logger, resumable_source_manager, resume
        )
        return

    if config.pagination == "fanout_offset":
        platform = _require_identifier(balance_platform, "Balance platform ID")
        start_parent_index = resume.parent_index if resume is not None and resume.parent_index is not None else 0
        yield from _iter_fanout_pages(
            session, config, host, platform, logger, resumable_source_manager, start_parent_index
        )
        return

    if config.pagination == "offset":
        platform = _require_identifier(balance_platform, "Balance platform ID")
        path = config.path.format(balance_platform=platform)
        start_offset = resume.offset if resume is not None and resume.offset is not None else 0

        def checkpoint(offset: int) -> None:
            resumable_source_manager.save_state(AdyenResumeConfig(offset=offset))

        yield from _iter_offset_pages(
            session, host, path, config.data_key, logger, start_offset=start_offset, on_page=checkpoint
        )
        return

    start_page = resume.page_number if resume is not None and resume.page_number is not None else 1
    yield from _iter_page_number_pages(
        session, host, config.path, config.data_key, logger, resumable_source_manager, start_page
    )


def adyen_source(
    environment: Optional[str],
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AdyenResumeConfig],
    balance_platform: Optional[str] = None,
    merchant_account: Optional[str] = None,
    start_date: Optional[str] = None,
    settlement_report_start_batch: Optional[int] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = ADYEN_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            environment=environment,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            balance_platform=balance_platform,
            merchant_account=merchant_account,
            start_date=start_date,
            settlement_report_start_batch=settlement_report_start_batch,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=list(config.primary_key),
        # Every paginated endpoint is walked oldest-first (`sortOrder=asc`, ascending offsets,
        # ascending report batch numbers), so the incremental watermark only ever moves forward.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
