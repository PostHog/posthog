"""Checkout.com payments, payment actions, customers and instruments.

Bulk payment objects come from ``POST /payments/search`` (the one server-side
listing surface; ``GET /payments`` only looks up by reference). The search
request requires a non-empty ``query`` and supports ``from``/``to`` and
``limit`` (max 1000) but no documented page cursor, so listing walks the time
range and recursively splits any window that fills a whole page; a window
returning fewer than ``limit`` rows is provably complete. Documented search
coverage is roughly the previous 90 days, so range starts are clamped to that
horizon; older history is only available via the report tables.

``payment_actions``, ``customers`` and ``instruments`` have no listing
endpoints at all, so their syncs walk the same payment windows and fan out to
``GET /payments/{id}/actions``, ``GET /customers/{id}`` and
``GET /instruments/{id}`` for the ids those payments reference.
"""

import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.checkout_com import (
    CheckoutComResumeConfig,
    _error_details,
    _format_timestamp,
    _hosts,
    _make_auth,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.reports import (
    _make_api_session,
    _strip_links,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import OAuth2Auth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

PAYMENTS_ENDPOINTS = ("payments", "payment_actions", "customers", "instruments")

# The search endpoint caps `limit` at 1000.
SEARCH_PAGE_LIMIT = 1000
# The search endpoint rejects a request without a non-empty `query` as unprocessable
# (422), and Checkout.com documents no match-all expression, so the widest valid
# filter is a predicate every payment satisfies. Comparisons use the colon-prefixed
# form (`field:>=value`) to match the documented `field:value` grammar; a bare
# `amount>=0` appears in no official example.
SEARCH_MATCH_ALL_QUERY = "amount:>=0"
# Checkout.com documents payments search as covering roughly the previous 90 days, so
# this is both the default backfill reach and the clamp for configured start dates and
# stale watermarks; anything older can't come back from search.
SEARCH_HORIZON = timedelta(days=90)
REQUEST_TIMEOUT_SECONDS = 120
# A window that still fills a whole page at this span can't be split further; anything
# past it is yielded with an error log rather than silently truncated.
MIN_WINDOW = timedelta(seconds=1)
# The search endpoint's documented behaviour is a 90-day default lookback when no range
# is given, with no documented support for much larger custom ranges; a full backfill
# window (up to `DEFAULT_BACKFILL_DAYS`) sent as one request 422s in practice. Chunking
# the overall sync range to this span keeps every request within the documented norm;
# each chunk is still split further on page-fullness as before.
MAX_SEARCH_WINDOW = timedelta(days=90)
# Bound one sync's API usage: searches are one call per ~1000 payments, fan-out lookups
# are one call per payment/customer/instrument. A capped run stops after the last fully
# processed window, so the next run continues from its watermark.
MAX_SEARCH_REQUESTS_PER_SYNC = 2_000
MAX_FANOUT_LOOKUPS_PER_SYNC = 10_000
FANOUT_CHUNK_SIZE = 500


class _SyncBudget:
    """Counts API calls for one sync and says when to stop cleanly."""

    def __init__(self, searches: int, lookups: int) -> None:
        self.searches_left = searches
        self.lookups_left = lookups
        self.exhausted = False


@dataclasses.dataclass(frozen=True, kw_only=True)
class _Window:
    start: datetime
    end: datetime


def _to_datetime(value: Any) -> datetime | None:
    """Coerce a stored watermark or configured start date (datetime, date or ISO string) into UTC."""
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


def _resolve_start(
    start_date: Optional[str],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    resume_window_to: Optional[str],
    now: datetime,
) -> datetime:
    # A resume checkpoint is always at or past the incremental watermark, so it wins.
    resumed = _to_datetime(resume_window_to)
    if resumed is not None:
        return resumed
    if should_use_incremental_field:
        watermark = _to_datetime(db_incremental_field_last_value)
        if watermark is not None:
            return watermark
    configured = _to_datetime(start_date) if start_date else None
    if configured is not None:
        return configured
    return now - SEARCH_HORIZON


def _search_payments(
    session: requests.Session,
    auth: OAuth2Auth,
    api_base: str,
    window: _Window,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    body = {
        "query": SEARCH_MATCH_ALL_QUERY,
        "from": _format_timestamp(window.start),
        "to": _format_timestamp(window.end),
        "limit": SEARCH_PAGE_LIMIT,
    }
    response = session.post(f"{api_base}/payments/search", json=body, auth=auth, timeout=REQUEST_TIMEOUT_SECONDS)
    if not response.ok:
        logger.error(
            f"Checkout.com API error: status={response.status_code}, "
            f"url={api_base}/payments/search, body={_error_details(response)}"
        )
        response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return []
    return [payment for payment in data if isinstance(payment, dict)]


def _iter_payment_windows(
    session: requests.Session,
    auth: OAuth2Auth,
    api_base: str,
    window: _Window,
    logger: FilteringBoundLogger,
    budget: _SyncBudget,
) -> Iterator[tuple[_Window, list[dict[str, Any]]]]:
    """Yield ascending, provably complete windows of payments.

    A page holding exactly ``SEARCH_PAGE_LIMIT`` rows may have dropped results, so
    that window is split in half and re-queried (left half first, preserving
    ascending order) until it fits in one page or reaches ``MIN_WINDOW``.
    """
    if window.end <= window.start:
        return
    if budget.searches_left <= 0:
        budget.exhausted = True
        return
    budget.searches_left -= 1

    payments = _search_payments(session, auth, api_base, window, logger)
    if len(payments) < SEARCH_PAGE_LIMIT or (window.end - window.start) <= MIN_WINDOW:
        if len(payments) >= SEARCH_PAGE_LIMIT:
            logger.error(
                "Checkout.com payments window is full at the minimum span; some payments in it may be missing",
                window_start=_format_timestamp(window.start),
                window_end=_format_timestamp(window.end),
            )
        payments.sort(key=lambda payment: (str(payment.get("requested_on") or ""), str(payment.get("id") or "")))
        yield window, payments
        return

    middle = window.start + (window.end - window.start) / 2
    yield from _iter_payment_windows(session, auth, api_base, _Window(start=window.start, end=middle), logger, budget)
    yield from _iter_payment_windows(session, auth, api_base, _Window(start=middle, end=window.end), logger, budget)


def _iter_bounded_payment_windows(
    session: requests.Session,
    auth: OAuth2Auth,
    api_base: str,
    start: datetime,
    end: datetime,
    logger: FilteringBoundLogger,
    budget: _SyncBudget,
) -> Iterator[tuple[_Window, list[dict[str, Any]]]]:
    """Walk the full sync range in `MAX_SEARCH_WINDOW`-sized chunks, each further split
    by `_iter_payment_windows` on page-fullness."""
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + MAX_SEARCH_WINDOW, end)
        yield from _iter_payment_windows(session, auth, api_base, _Window(start=cursor, end=chunk_end), logger, budget)
        if budget.exhausted:
            return
        cursor = chunk_end


def _fanout_get(
    session: requests.Session,
    auth: OAuth2Auth,
    url: str,
    logger: FilteringBoundLogger,
) -> Optional[dict[str, Any] | list[Any]]:
    """One fan-out GET; a 404 means the record no longer exists and is skipped."""
    response = session.get(url, auth=auth, timeout=REQUEST_TIMEOUT_SECONDS)
    if response.status_code == 404:
        return None
    if not response.ok:
        logger.error(
            f"Checkout.com API error: status={response.status_code}, url={url}, body={_error_details(response)}"
        )
        response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict | list) else None


def _extract_action_items(payload: dict[str, Any] | list[Any] | None) -> list[dict[str, Any]]:
    # The SDKs model the actions response as an `items` wrapper; accept a bare array
    # and a `data` wrapper too so a representation change doesn't zero the table.
    if isinstance(payload, list):
        items: Any = payload
    elif isinstance(payload, dict):
        items = payload.get("items") if isinstance(payload.get("items"), list) else payload.get("data")
    else:
        items = None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _payment_actions_rows(
    session: requests.Session,
    auth: OAuth2Auth,
    api_base: str,
    payment: dict[str, Any],
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    payment_id = str(payment.get("id") or "")
    payload = _fanout_get(session, auth, f"{api_base}/payments/{payment_id}/actions", logger)
    rows = []
    for action in _extract_action_items(payload):
        row = _strip_links(action)
        # The parent payment's id and request time key the row to its payment and
        # carry the incremental watermark; they always win over same-named fields.
        row["payment_id"] = payment_id
        row["payment_requested_on"] = payment.get("requested_on")
        rows.append(row)
    return rows


def _referenced_id(payment: dict[str, Any], endpoint: str) -> Optional[str]:
    if endpoint == "customers":
        customer = payment.get("customer")
        raw = customer.get("id") if isinstance(customer, dict) else None
        prefix = "cus_"
    else:
        source = payment.get("source")
        raw = source.get("id") if isinstance(source, dict) else None
        prefix = "src_"
    value = str(raw or "")
    # Only vault-stored records are fetchable; other source ids (tokens, one-off
    # payment methods) have no GET endpoint.
    return value if value.startswith(prefix) else None


def _referenced_record_row(
    session: requests.Session,
    auth: OAuth2Auth,
    api_base: str,
    endpoint: str,
    record_id: str,
    payment: dict[str, Any],
    logger: FilteringBoundLogger,
) -> Optional[dict[str, Any]]:
    payload = _fanout_get(session, auth, f"{api_base}/{endpoint}/{record_id}", logger)
    if not isinstance(payload, dict):
        return None
    row = _strip_links(payload)
    row["payment_requested_on"] = payment.get("requested_on")
    return row


def _get_rows(
    environment: str,
    client_id: str,
    client_secret: str,
    schema_name: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CheckoutComResumeConfig],
    start_date: Optional[str],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> Iterator[list[dict[str, Any]]]:
    hosts = _hosts(environment)
    auth = _make_auth(environment, client_id, client_secret)
    session = _make_api_session(client_secret)
    budget = _SyncBudget(searches=MAX_SEARCH_REQUESTS_PER_SYNC, lookups=MAX_FANOUT_LOOKUPS_PER_SYNC)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    now = datetime.now(UTC)
    start = _resolve_start(
        start_date,
        should_use_incremental_field,
        db_incremental_field_last_value,
        resume.search_window_to if resume is not None else None,
        now,
    )
    horizon_start = now - SEARCH_HORIZON
    if start < horizon_start:
        logger.warning(
            "Checkout.com payments search covers roughly the previous 90 days; clamping the range start",
            requested_start=_format_timestamp(start),
            clamped_start=_format_timestamp(horizon_start),
        )
        start = horizon_start

    seen_ids: set[str] = set()
    chunk: list[dict[str, Any]] = []
    for window, payments in _iter_bounded_payment_windows(session, auth, hosts["api"], start, now, logger, budget):
        for payment in payments:
            if schema_name == "payments":
                chunk.append(_strip_links(payment))
            elif schema_name == "payment_actions":
                if not str(payment.get("id") or ""):
                    continue
                if budget.lookups_left <= 0:
                    budget.exhausted = True
                    break
                budget.lookups_left -= 1
                chunk.extend(_payment_actions_rows(session, auth, hosts["api"], payment, logger))
            else:
                record_id = _referenced_id(payment, schema_name)
                if record_id is None or record_id in seen_ids:
                    continue
                seen_ids.add(record_id)
                if budget.lookups_left <= 0:
                    budget.exhausted = True
                    break
                budget.lookups_left -= 1
                row = _referenced_record_row(session, auth, hosts["api"], schema_name, record_id, payment, logger)
                if row is not None:
                    chunk.append(row)
            if len(chunk) >= FANOUT_CHUNK_SIZE:
                yield chunk
                chunk = []
        if budget.exhausted:
            # The interrupted window is not checkpointed, so the next attempt or the
            # next scheduled sync re-covers it (merge dedupes overlapping rows).
            break
        resumable_source_manager.save_state(CheckoutComResumeConfig(search_window_to=_format_timestamp(window.end)))
    if budget.exhausted:
        logger.warning(
            "Checkout.com sync hit its per-run API budget; continuing from the last complete window next run",
            schema=schema_name,
        )
    if chunk:
        yield chunk


def checkout_com_payments_source(
    environment: str,
    client_id: str,
    client_secret: str,
    schema_name: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CheckoutComResumeConfig],
    start_date: Optional[str] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    if schema_name not in PAYMENTS_ENDPOINTS:
        raise ValueError(f"Unknown Checkout.com schema: {schema_name}")

    if schema_name == "payments":
        primary_keys = ["id"]
        partition_keys: Optional[list[str]] = ["requested_on"]
    elif schema_name == "payment_actions":
        # Action ids look globally unique, but the API doesn't document that scope,
        # so the parent payment id is part of the key.
        primary_keys = ["payment_id", "id"]
        partition_keys = ["payment_requested_on"]
    else:
        # Customers and instruments are point lookups keyed by their own id; they
        # carry no stable creation timestamp to partition on.
        primary_keys = ["id"]
        partition_keys = None

    return SourceResponse(
        name=schema_name,
        items=lambda: _get_rows(
            environment=environment,
            client_id=client_id,
            client_secret=client_secret,
            schema_name=schema_name,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            start_date=start_date,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=primary_keys,
        partition_count=1 if partition_keys else None,
        partition_size=1 if partition_keys else None,
        partition_mode="datetime" if partition_keys else None,
        partition_format="month" if partition_keys else None,
        partition_keys=partition_keys,
        # Windows walk oldest-first and each window is sorted before yielding, so the
        # watermark only moves forward.
        sort_mode="asc",
    )
