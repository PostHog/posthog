"""Checkout.com payments, payment actions, customers and instruments.

Bulk payment objects come from ``POST /payments/search`` (the one server-side
listing surface; ``GET /payments`` only looks up by reference). The search
request requires a non-empty ``query`` and supports ``from``/``to`` and
``limit`` (max 1000) but no documented page cursor, so listing walks the time
range and recursively splits any window that fills a whole page; a window
returning fewer than ``limit`` rows is provably complete. Documented search
coverage is roughly the previous 90 days, which sets how far back a first sync
reaches; the endpoint serves older payments too, so a configured ``start_date``
reaching further back is honoured rather than clamped forward.

A sync bounds its own API usage with per-run call budgets. Hitting one leaves the
range incomplete, so it raises: returning would report the schema ``Completed``
over months holding no rows. Each fully-drained window is checkpointed, so the
retry resumes where the budget ran out.

``payment_actions``, ``customers`` and ``instruments`` have no listing
endpoints at all, so their syncs walk the same payment windows and fan out per
referenced record. The search response references a customer by email alone
(its ``customer`` object carries no ``cus_`` id) and describes a card source
without an instrument id, so customers are fetched via ``GET
/customers/{identifier}`` (the endpoint accepts an email) and instruments via
``GET /payments/{id}`` (whose detail response carries the source id) followed
by ``GET /instruments/{id}``. Payment rows get a ``customer_id`` column from
the same customer lookups so they join to the customers table.
"""

import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import quote

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    PartitionFormat,
    PartitionMode,
    SourceResponse,
)

PAYMENTS_ENDPOINTS = ("payments", "payment_actions", "customers", "instruments")

# The search endpoint caps `limit` at 1000.
SEARCH_PAGE_LIMIT = 1000
# The search endpoint rejects a request without a non-empty `query` as unprocessable
# (422), and Checkout.com documents no match-all expression, so the widest valid
# filter is a predicate every payment satisfies. Comparisons use the colon-prefixed
# form (`field:>=value`) to match the documented `field:value` grammar; a bare
# `amount>=0` appears in no official example.
SEARCH_MATCH_ALL_QUERY = "amount:>=0"
# Checkout.com documents payments search as covering roughly the previous 90 days, so this
# is how far back a first sync reaches when nothing else says otherwise. It is a default,
# not a limit: the endpoint serves well past its documented window, so a configured
# `start_date` reaching further back is honoured rather than clamped forward.
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
# are one call per referenced payment/customer/instrument. A capped run stops after the
# last fully processed window, so the next run continues from its watermark.
MAX_SEARCH_REQUESTS_PER_SYNC = 2_000
MAX_FANOUT_LOOKUPS_PER_SYNC = 10_000
# The payments schema enriches each row with `customer_id` via one `GET
# /customers/{email}` per unique email per run (see _CustomerIdResolver). The cap bounds
# a pathological backfill; past it, rows keep syncing with `customer_id` null. This is
# deliberately a soft stop, unlike the fan-out budget: covered windows are checkpointed
# and never re-read, so raising could not backfill the nulls anyway.
MAX_CUSTOMER_ID_LOOKUPS_PER_SYNC = 10_000
FANOUT_CHUNK_SIZE = 500
# Bucket count for the md5(id) partitioning of `payments` (see
# checkout_com_payments_source): enough buckets to keep each per-partition merge small
# on multi-million-row accounts, matching the count other id-hashed sources use.
PAYMENTS_PARTITION_COUNT = 200

# Only vault-stored records are fetchable; other source ids (tokens, one-off payment
# methods) have no GET endpoint.
CUSTOMER_ID_PREFIX = "cus_"
INSTRUMENT_ID_PREFIX = "src_"

# Stable marker so the source can classify a budget stop as retryable rather than a bug.
SYNC_BUDGET_EXCEEDED_MARKER = "Checkout.com sync hit its per-run API budget"
# Stable marker so the source can map an id-less run to a customer-facing error.
UNRESOLVED_REFERENCES_MARKER = "Checkout.com payments reference records without a usable identifier"


class CheckoutComSyncBudgetExceeded(Exception):
    """A sync stopped at its per-run API call budget before covering its whole range.

    Raised rather than returned. Returning cleanly reported the schema `Completed` with no
    error while the range past the cut-off held no rows at all, so the gap was invisible:
    `last_synced_at` moved, the table did not. Every window completed before the budget ran
    out is checkpointed, so the retry resumes there instead of redoing the run.
    """


class CheckoutComUnresolvedReferencesError(Exception):
    """Every reference a customers/instruments run saw was impossible to look up.

    Raised rather than returned. Returning would report the schema `Completed` while the
    table silently stays empty, hiding that the account's payments carry references we
    cannot resolve. A run that resolves at least one reference completes and only logs
    the leftover count: partial data with a visible log beats pausing a working table.
    """


class _SyncBudget:
    """Counts API calls for one sync and says when to stop cleanly."""

    def __init__(self, searches: int, lookups: int) -> None:
        self.searches_left = searches
        self.lookups_left = lookups
        self.exhausted = False

    def take_lookup(self) -> bool:
        """Consume one fan-out lookup; False (and exhausted) once the budget is spent."""
        if self.lookups_left <= 0:
            self.exhausted = True
            return False
        self.lookups_left -= 1
        return True


@dataclasses.dataclass(frozen=True, kw_only=True)
class _Window:
    start: datetime
    end: datetime


@dataclasses.dataclass(frozen=True, kw_only=True)
class _CardIdentity:
    """One customer's use of one card, the granularity payment-detail lookups dedupe on.

    Payments sharing a fingerprint alone can still resolve to different instruments (two
    customers storing the same card), so the holder's email is part of the key. A payment
    whose customer carries no usable email has no identity at all: keying it on the
    fingerprint alone would let one customer's instrument stand in for another's, so such
    payments resolve individually instead of sharing a cache entry.
    """

    fingerprint: str
    customer_email: str


@dataclasses.dataclass(frozen=False)
class _FanoutRunState:
    """Dedupe sets, caches and resolution counters shared across one run's windows."""

    seen_keys: set[str] = dataclasses.field(default_factory=set)
    instrument_ids_by_card: dict[_CardIdentity, Optional[str]] = dataclasses.field(default_factory=dict)
    unresolvable_references: int = 0
    rows_landed: int = 0


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


def _customer_email(customer: dict[str, Any]) -> Optional[str]:
    email = str(customer.get("email") or "").strip()
    return email if "@" in email else None


def _customer_identifier(customer: dict[str, Any]) -> Optional[str]:
    """The value ``GET /customers/{identifier}`` accepts for this payment's customer.

    The endpoint takes a ``cus_`` id or an email address. The search response usually
    carries only the email (its ``customer`` object omits the id), so the email is the
    primary route to the record rather than a fallback.
    """
    raw_id = str(customer.get("id") or "")
    if raw_id.startswith(CUSTOMER_ID_PREFIX):
        return raw_id
    return _customer_email(customer)


def _fetch_customer(
    session: requests.Session,
    auth: OAuth2Auth,
    api_base: str,
    identifier: str,
    logger: FilteringBoundLogger,
) -> Optional[dict[str, Any]]:
    """One customer lookup by ``cus_`` id or email; None when no such customer exists.

    Email identifiers are personal data, and both job logs and ``latest_error`` are
    readable by anyone with project access. This module's own log lines and raised error
    messages show an ``{email}`` placeholder, and the tracked transport masks the address
    out of the request URL it records (``url_utils.scrub_url``), so neither carries it.
    """
    is_email = "@" in identifier
    url = f"{api_base}/customers/{quote(identifier, safe='')}"
    display_url = f"{api_base}/customers/{{email}}" if is_email else url
    response = session.get(url, auth=auth, timeout=REQUEST_TIMEOUT_SECONDS)
    if response.status_code == 404:
        return None
    if not response.ok:
        logger.error(
            f"Checkout.com API error: status={response.status_code}, url={display_url}, body={_error_details(response)}"
        )
        if not is_email:
            response.raise_for_status()
        kind = "Client Error" if response.status_code < 500 else "Server Error"
        reason = str(getattr(response, "reason", "") or "")
        raise requests.HTTPError(
            f"{response.status_code} {kind}: {reason} for url: {display_url}",
            response=response,
        )
    payload = response.json()
    return payload if isinstance(payload, dict) else None


class _CustomerIdResolver:
    """Fills the ``customer_id`` column on payment rows.

    ``/payments/search`` returns customers as an email with no ``cus_`` id, so the id
    that joins payments to the customers table has to come from ``GET /customers/{email}``:
    one call per unique email per run, with misses cached too. The column is enrichment on
    top of otherwise-complete payment rows, so resolution degrades to null instead of
    failing the payments sync: a 401/403 (an access key without the vault scope) or the
    per-run lookup cap stops further lookups for the run.
    """

    def __init__(
        self,
        session: requests.Session,
        auth: OAuth2Auth,
        api_base: str,
        logger: FilteringBoundLogger,
    ) -> None:
        self._session = session
        self._auth = auth
        self._api_base = api_base
        self._logger = logger
        self._ids_by_email: dict[str, Optional[str]] = {}
        self._lookups_left = MAX_CUSTOMER_ID_LOOKUPS_PER_SYNC
        self._stopped = False

    def resolve(self, payment: dict[str, Any]) -> Optional[str]:
        customer = payment.get("customer")
        if not isinstance(customer, dict):
            return None
        raw_id = str(customer.get("id") or "")
        if raw_id.startswith(CUSTOMER_ID_PREFIX):
            return raw_id
        email = _customer_email(customer)
        if email is None:
            return None
        key = email.lower()
        if key in self._ids_by_email:
            return self._ids_by_email[key]
        if self._stopped:
            return None
        if self._lookups_left <= 0:
            self._stop("the per-run customer lookup cap was reached")
            return None
        self._lookups_left -= 1
        try:
            record = _fetch_customer(self._session, self._auth, self._api_base, email, self._logger)
        except requests.HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status in (401, 403):
                self._stop("Checkout.com denied customer lookups (the access key lacks the vault scope)")
                return None
            raise
        resolved: Optional[str] = None
        if record is not None:
            value = str(record.get("id") or "")
            if value.startswith(CUSTOMER_ID_PREFIX):
                resolved = value
        self._ids_by_email[key] = resolved
        return resolved

    def _stop(self, reason: str) -> None:
        self._stopped = True
        self._logger.warning(
            f"Stopping payments customer_id resolution for this run: {reason}; "
            "remaining rows sync with customer_id null"
        )


def _customer_row(
    session: requests.Session,
    auth: OAuth2Auth,
    api_base: str,
    payment: dict[str, Any],
    logger: FilteringBoundLogger,
    budget: _SyncBudget,
    state: _FanoutRunState,
) -> Optional[dict[str, Any]]:
    customer = payment.get("customer")
    if not isinstance(customer, dict) or not customer:
        return None
    identifier = _customer_identifier(customer)
    if identifier is None:
        state.unresolvable_references += 1
        return None
    key = identifier.lower()
    if key in state.seen_keys:
        return None
    state.seen_keys.add(key)
    if not budget.take_lookup():
        return None
    record = _fetch_customer(session, auth, api_base, identifier, logger)
    if record is None:
        return None
    row = _strip_links(record)
    record_id = str(row.get("id") or "")
    if not record_id:
        # Without an id the row can't be merged on the table's primary key.
        return None
    # An email lookup teaches us the id, so a later payment carrying the raw id
    # doesn't fetch the same customer again.
    state.seen_keys.add(record_id.lower())
    row["payment_requested_on"] = payment.get("requested_on")
    return row


def _card_identity(payment: dict[str, Any]) -> Optional[_CardIdentity]:
    source = payment.get("source")
    fingerprint = str(source.get("fingerprint") or "") if isinstance(source, dict) else ""
    if not fingerprint:
        return None
    customer = payment.get("customer")
    email = _customer_email(customer) if isinstance(customer, dict) else None
    if not email:
        return None
    return _CardIdentity(fingerprint=fingerprint, customer_email=email.lower())


def _payment_detail_instrument_id(
    session: requests.Session,
    auth: OAuth2Auth,
    api_base: str,
    payment_id: str,
    logger: FilteringBoundLogger,
) -> Optional[str]:
    """The vault instrument id behind one payment, from ``GET /payments/{id}``.

    The search response's ``source`` describes the card (fingerprint, bin, last4) but
    carries no id; the detail response includes the full source object. A detail whose
    source still has no ``src_`` id means the payment wasn't made with a vault-stored
    instrument, which is an answer rather than a failure.
    """
    payload = _fanout_get(session, auth, f"{api_base}/payments/{quote(payment_id, safe='')}", logger)
    if not isinstance(payload, dict):
        return None
    source = payload.get("source")
    raw = source.get("id") if isinstance(source, dict) else None
    value = str(raw or "")
    return value if value.startswith(INSTRUMENT_ID_PREFIX) else None


def _instrument_record_row(
    session: requests.Session,
    auth: OAuth2Auth,
    api_base: str,
    record_id: str,
    payment: dict[str, Any],
    logger: FilteringBoundLogger,
) -> Optional[dict[str, Any]]:
    payload = _fanout_get(session, auth, f"{api_base}/instruments/{quote(record_id, safe='')}", logger)
    if not isinstance(payload, dict):
        return None
    row = _strip_links(payload)
    row["payment_requested_on"] = payment.get("requested_on")
    return row


def _instrument_row(
    session: requests.Session,
    auth: OAuth2Auth,
    api_base: str,
    payment: dict[str, Any],
    logger: FilteringBoundLogger,
    budget: _SyncBudget,
    state: _FanoutRunState,
) -> Optional[dict[str, Any]]:
    source = payment.get("source")
    if not isinstance(source, dict) or not source:
        return None
    record_id_value = str(source.get("id") or "")
    record_id: Optional[str] = record_id_value if record_id_value.startswith(INSTRUMENT_ID_PREFIX) else None
    if record_id is None:
        payment_id = str(payment.get("id") or "")
        if not payment_id:
            # No id to fetch payment details with, so the reference is a dead end.
            state.unresolvable_references += 1
            return None
        card = _card_identity(payment)
        if card is not None and card in state.instrument_ids_by_card:
            record_id = state.instrument_ids_by_card[card]
        else:
            if not budget.take_lookup():
                return None
            record_id = _payment_detail_instrument_id(session, auth, api_base, payment_id, logger)
            if card is not None:
                state.instrument_ids_by_card[card] = record_id
        if record_id is None:
            return None
    if record_id in state.seen_keys:
        return None
    state.seen_keys.add(record_id)
    if not budget.take_lookup():
        return None
    return _instrument_record_row(session, auth, api_base, record_id, payment, logger)


def _report_unresolved_references(schema_name: str, state: _FanoutRunState, logger: FilteringBoundLogger) -> None:
    noun = "customer" if schema_name == "customers" else "payment instrument"
    if state.rows_landed == 0:
        raise CheckoutComUnresolvedReferencesError(
            f"{UNRESOLVED_REFERENCES_MARKER}: {state.unresolvable_references} payment(s) in this run "
            f"reference a {noun} that carries no fetchable identifier, and no {schema_name} could be resolved"
        )
    logger.error(
        f"Checkout.com {schema_name} sync left {state.unresolvable_references} payment reference(s) "
        "unresolved: those payments carry no fetchable identifier"
    )


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
    state = _FanoutRunState()
    customer_ids = _CustomerIdResolver(session, auth, hosts["api"], logger) if schema_name == "payments" else None

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    now = datetime.now(UTC)
    start = _resolve_start(
        start_date,
        should_use_incremental_field,
        db_incremental_field_last_value,
        resume.search_window_to if resume is not None else None,
        now,
    )
    chunk: list[dict[str, Any]] = []
    for window, payments in _iter_bounded_payment_windows(session, auth, hosts["api"], start, now, logger, budget):
        for payment in payments:
            if schema_name == "payments":
                payment_row = _strip_links(payment)
                # Search rows reference their customer without a `cus_` id, so the id that
                # keys the join to the customers table is resolved separately; it always
                # wins over a same-named field.
                payment_row["customer_id"] = customer_ids.resolve(payment) if customer_ids is not None else None
                chunk.append(payment_row)
            elif schema_name == "payment_actions":
                if not str(payment.get("id") or ""):
                    continue
                if not budget.take_lookup():
                    break
                chunk.extend(_payment_actions_rows(session, auth, hosts["api"], payment, logger))
            else:
                row = (
                    _customer_row(session, auth, hosts["api"], payment, logger, budget, state)
                    if schema_name == "customers"
                    else _instrument_row(session, auth, hosts["api"], payment, logger, budget, state)
                )
                if budget.exhausted:
                    break
                if row is not None:
                    state.rows_landed += 1
                    chunk.append(row)
            if len(chunk) >= FANOUT_CHUNK_SIZE:
                yield chunk
                chunk = []
        if budget.exhausted:
            # The interrupted window is not checkpointed, so the next attempt or the
            # next scheduled sync re-covers it (merge dedupes overlapping rows).
            break
        resumable_source_manager.save_state(CheckoutComResumeConfig(search_window_to=_format_timestamp(window.end)))
    if chunk:
        yield chunk
    if budget.exhausted:
        raise CheckoutComSyncBudgetExceeded(
            f"{SYNC_BUDGET_EXCEEDED_MARKER} for {schema_name} before reaching "
            f"{_format_timestamp(now)}; the range past the last complete window holds no rows yet"
        )
    if state.unresolvable_references:
        _report_unresolved_references(schema_name, state, logger)


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
        # The merge matches on primary key *and* partition, and every sync re-reads
        # `requested_on` from the search index, which does not promise the same value
        # (or any value at all) for a payment across fetches. A timestamp-keyed
        # partition can therefore shift between two runs that cover the same payment,
        # and the merge inserts a second copy it can never match instead of updating
        # the first, so duplicate ids accumulate. Hashing the immutable id gives every
        # payment one partition for good while keeping merges partition-bounded.
        partition_keys: Optional[list[str]] = ["id"]
        partition_mode: Optional[PartitionMode] = "md5"
        partition_format: Optional[PartitionFormat] = None
        partition_count: Optional[int] = PAYMENTS_PARTITION_COUNT
    elif schema_name == "payment_actions":
        # Action ids look globally unique, but the API doesn't document that scope,
        # so the parent payment id is part of the key.
        primary_keys = ["payment_id", "id"]
        partition_keys = ["payment_requested_on"]
        partition_mode = "datetime"
        partition_format = "month"
        partition_count = 1
    else:
        # Customers and instruments are point lookups keyed by their own id; they
        # carry no stable creation timestamp to partition on.
        primary_keys = ["id"]
        partition_keys = None
        partition_mode = None
        partition_format = None
        partition_count = None

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
        partition_count=partition_count,
        partition_size=1 if partition_keys else None,
        partition_mode=partition_mode,
        partition_format=partition_format,
        partition_keys=partition_keys,
        # Windows walk oldest-first and each window is sorted before yielding, so the
        # watermark only moves forward.
        sort_mode="asc",
    )
