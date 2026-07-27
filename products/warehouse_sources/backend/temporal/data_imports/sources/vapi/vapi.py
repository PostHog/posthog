import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import pyarrow as pa
import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.vapi.settings import (
    DEFAULT_PAGE_LIMIT,
    VAPI_BASE_URL,
    VAPI_ENDPOINTS,
    VapiEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60

REDACTED_VALUE = "[REDACTED]"

# Vapi list responses embed auth material inside otherwise-analytical rows: assistant/call
# `credentials` arrays (provider API keys), tool and server `headers` (commonly Authorization),
# webhook `secret`s, and Twilio auth fields on phone numbers. Redact them by key before rows
# reach the warehouse — anyone with warehouse read access can query synced columns. Bare
# `credentialId`/`credentialIds` are UUID references, not secrets, and are kept.
_SENSITIVE_EXACT_KEYS = frozenset({"credentials", "headers"})
_SENSITIVE_KEY_SUBSTRINGS = ("secret", "password", "authtoken", "apikey")


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in _SENSITIVE_EXACT_KEYS or any(part in lowered for part in _SENSITIVE_KEY_SUBSTRINGS)


def _scrub_sensitive_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: REDACTED_VALUE if _is_sensitive_key(k) else _scrub_sensitive_values(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_sensitive_values(item) for item in value]
    return value


class VapiRetryableError(Exception):
    pass


@dataclasses.dataclass
class VapiResumeConfig:
    # createdAt of the last row already yielded downstream. On resume, descending endpoints
    # request `createdAtLt=<cursor>` and ascending page endpoints restart at page 1 with
    # `createdAtGt=<cursor>` — both skip exactly the rows already delivered. A distinct row
    # sharing the boundary's millisecond timestamp would be skipped too; Vapi timestamps have
    # millisecond precision so collisions are vanishingly rare.
    created_at_cursor: str | None = None


def _format_datetime_param(value: Any) -> str:
    """Format an incremental cursor as the ISO 8601 Z-suffixed string Vapi returns and accepts."""
    if isinstance(value, datetime):
        utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return _format_datetime_param(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


def _make_session(api_key: str) -> requests.Session:
    # capture=False: Vapi response bodies carry secrets under names the sample-capture
    # scrubbers don't recognise (`credentials` arrays, `twilioAuthToken`, webhook `secret`,
    # header maps) — see `_scrub_sensitive_values`, which only protects the warehouse path.
    return make_tracked_session(
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        redact_values=(api_key,),
        capture=False,
    )


@retry(
    retry=retry_if_exception_type(
        (
            VapiRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(session: requests.Session, url: str, logger: FilteringBoundLogger) -> Any:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise VapiRetryableError(f"Vapi API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Vapi API error: status={response.status_code}, body={response.text[:500]}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str) -> bool:
    url = f"{VAPI_BASE_URL}/assistant?{urlencode({'limit': 1})}"
    try:
        response = _make_session(api_key).get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        return response.status_code == 200
    except Exception:
        return False


def _last_created_at(table: pa.Table) -> str | None:
    if "createdAt" not in table.column_names:
        return None
    value = table.column("createdAt")[-1].as_py()
    return value if isinstance(value, str) else None


def _fetch_created_at_desc_pages(
    session: requests.Session,
    config: VapiEndpointConfig,
    logger: FilteringBoundLogger,
    base_params: dict[str, Any],
    created_at_lt: str | None,
) -> Iterator[list[dict[str, Any]]]:
    """Walk a createdAt-descending array endpoint, cursoring with `createdAtLt`."""
    cursor = created_at_lt

    while True:
        params: dict[str, Any] = {**base_params, "limit": DEFAULT_PAGE_LIMIT}
        if cursor:
            # Overrides any createdAtLt in base_params: the cursor only ever moves further back.
            params["createdAtLt"] = cursor
        url = f"{VAPI_BASE_URL}{config.path}?{urlencode(params)}"

        rows = _fetch(session, url, logger)
        if not isinstance(rows, list) or len(rows) == 0:
            return

        yield rows

        if len(rows) < DEFAULT_PAGE_LIMIT:
            return

        cursor = rows[-1].get("createdAt")
        if not cursor:
            logger.warning(f"Vapi: {config.name} row missing createdAt, stopping pagination")
            return


def _fetch_ascending_pages(
    session: requests.Session,
    config: VapiEndpointConfig,
    logger: FilteringBoundLogger,
    base_params: dict[str, Any],
) -> Iterator[list[dict[str, Any]]]:
    """Walk a `{results, metadata}` endpoint page by page in ascending createdAt order.

    ASC ordering keeps page boundaries stable under concurrent inserts (new rows land after the
    pages already read); rows deleted mid-sync can still shift a boundary, which merge tolerates.
    """
    page = 1

    while True:
        params: dict[str, Any] = {
            **base_params,
            "limit": DEFAULT_PAGE_LIMIT,
            "page": page,
            "sortOrder": "ASC",
            "sortBy": "createdAt",
        }
        url = f"{VAPI_BASE_URL}{config.path}?{urlencode(params)}"

        data = _fetch(session, url, logger)
        rows = data.get("results", []) if isinstance(data, dict) else data
        if not isinstance(rows, list) or len(rows) == 0:
            return

        yield rows

        metadata = data.get("metadata", {}) if isinstance(data, dict) else {}
        has_next = metadata.get("hasNextPage") if isinstance(metadata, dict) else None
        if has_next is False or (has_next is None and len(rows) < DEFAULT_PAGE_LIMIT):
            return

        page += 1


def _drain(
    batcher: Batcher,
    resumable_source_manager: ResumableSourceManager[VapiResumeConfig],
    save_resume_state: bool,
    include_incomplete_chunk: bool = False,
) -> Iterator[pa.Table]:
    while batcher.should_yield(include_incomplete_chunk=include_incomplete_chunk):
        table = batcher.get_table()
        yield table

        # Save AFTER yielding, keyed to the last row actually delivered, so a crash re-yields
        # from the exact boundary instead of skipping rows still buffered in the batcher.
        if save_resume_state:
            cursor = _last_created_at(table)
            if cursor:
                resumable_source_manager.save_state(VapiResumeConfig(created_at_cursor=cursor))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[VapiResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    db_incremental_field_earliest_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> Iterator[pa.Table]:
    config = VAPI_ENDPOINTS[endpoint]
    session = _make_session(api_key)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    resume_cursor = resume.created_at_cursor if resume is not None else None

    if config.pagination == "none":
        rows = _fetch(session, f"{VAPI_BASE_URL}{config.path}", logger)
        if isinstance(rows, list) and rows:
            batcher.batch(_scrub_sensitive_values(rows))
        yield from _drain(batcher, resumable_source_manager, save_resume_state=False, include_incomplete_chunk=True)
        return

    advertised_fields = {f["field"] for f in config.incremental_fields}
    cursor_field = incremental_field if incremental_field in advertised_fields else "createdAt"
    incremental_active = (
        should_use_incremental_field
        and bool(advertised_fields)
        and (db_incremental_field_last_value is not None or db_incremental_field_earliest_value is not None)
    )

    if config.pagination == "created_at_cursor":
        if not incremental_active:
            # Full walk (initial sync or full refresh) — resumable via the createdAtLt cursor.
            for rows in _fetch_created_at_desc_pages(session, config, logger, {}, resume_cursor):
                batcher.batch(_scrub_sensitive_values(rows))
                yield from _drain(batcher, resumable_source_manager, save_resume_state=True)
            yield from _drain(batcher, resumable_source_manager, save_resume_state=True, include_incomplete_chunk=True)
            return

        # Incremental on a descending source (Stripe-style): first finish any historical backfill
        # (rows older than the earliest value seen), then fetch rows newer than the watermark.
        # Both legs are bounded windows, so a retry just re-fetches them and merge dedupes —
        # no resume state is saved or honored here.
        if db_incremental_field_earliest_value is not None:
            earliest = _format_datetime_param(db_incremental_field_earliest_value)
            logger.debug(f"Vapi: {endpoint} backfilling {cursor_field}Lt={earliest}")
            for rows in _fetch_created_at_desc_pages(session, config, logger, {f"{cursor_field}Lt": earliest}, None):
                batcher.batch(_scrub_sensitive_values(rows))
                yield from _drain(batcher, resumable_source_manager, save_resume_state=False)

        if db_incremental_field_last_value is not None:
            last = _format_datetime_param(db_incremental_field_last_value)
            logger.debug(f"Vapi: {endpoint} fetching {cursor_field}Gt={last}")
            for rows in _fetch_created_at_desc_pages(session, config, logger, {f"{cursor_field}Gt": last}, None):
                batcher.batch(_scrub_sensitive_values(rows))
                yield from _drain(batcher, resumable_source_manager, save_resume_state=False)

        yield from _drain(batcher, resumable_source_manager, save_resume_state=False, include_incomplete_chunk=True)
        return

    # Page-number endpoints, walked in ascending createdAt order. The resume cursor (createdAt of
    # the last row yielded) narrows the window with `createdAtGt` and restarts at page 1, which is
    # exact regardless of how many pages the batcher had buffered. An incremental watermark uses
    # the same mechanism; the cursor always supersedes it since it can only be newer.
    base_params: dict[str, Any] = {}
    effective_gt = resume_cursor
    if effective_gt is None and incremental_active and db_incremental_field_last_value is not None:
        effective_gt = _format_datetime_param(db_incremental_field_last_value)
    if effective_gt:
        base_params["createdAtGt"] = effective_gt

    for rows in _fetch_ascending_pages(session, config, logger, base_params):
        batcher.batch(_scrub_sensitive_values(rows))
        yield from _drain(batcher, resumable_source_manager, save_resume_state=True)
    yield from _drain(batcher, resumable_source_manager, save_resume_state=True, include_incomplete_chunk=True)


def vapi_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[VapiResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    db_incremental_field_earliest_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = VAPI_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            db_incremental_field_earliest_value=db_incremental_field_earliest_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        # created_at_cursor endpoints return newest-first, so the pipeline must track the
        # earliest/latest watermarks the Stripe way; page endpoints are requested ascending.
        sort_mode="desc" if config.pagination == "created_at_cursor" else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
