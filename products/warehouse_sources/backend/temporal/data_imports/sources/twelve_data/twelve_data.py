import dataclasses
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any, Optional

from requests import Session
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.twelve_data.settings import (
    ENDPOINTS,
    MAX_SYMBOLS,
    MAX_TIME_SERIES_PAGES_PER_SYMBOL,
    TIME_SERIES_ENDPOINT,
    TIME_SERIES_PAGE_SIZE,
    TWELVE_DATA_BASE_URL,
    TwelveDataEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60

# Rows per yielded batch for the large reference catalogs (the full /stocks dump is >100k rows).
CATALOG_CHUNK_SIZE = 5000


class TwelveDataError(Exception):
    pass


@dataclasses.dataclass
class TwelveDataResumeConfig:
    # Symbols whose rows were fully yielded this job; a resumed attempt skips them.
    completed_symbols: list[str] = dataclasses.field(default_factory=list)
    # Symbol mid-way through its time series back-walk, and the end_date the next page should use.
    current_symbol: str | None = None
    next_end_date: str | None = None


def parse_symbols(symbols: str) -> list[str]:
    """Split the user's comma-separated symbol list, dropping blanks and duplicates."""
    parsed = []
    for raw in symbols.split(","):
        symbol = raw.strip()
        if symbol and symbol not in parsed:
            parsed.append(symbol)
    return parsed


def _make_session(api_key: str) -> Session:
    return make_tracked_session(
        headers={"Authorization": f"apikey {api_key}"},
        redact_values=(api_key,),
    )


def _fetch(session: Session, path: str, params: dict[str, Any]) -> Any:
    """GET a Twelve Data endpoint, unwrapping the API's JSON error envelope.

    The API reports errors as ``{"code": ..., "message": ..., "status": "error"}`` — sometimes with a
    matching HTTP status, sometimes on HTTP 200 — so the body is inspected before the status code.
    Returns ``None`` when the requested date window simply has no rows (the API reports that as a
    code-400 error rather than an empty list).
    """
    response = session.get(f"{TWELVE_DATA_BASE_URL}{path}", params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    try:
        body = response.json()
    except ValueError:
        body = None

    if isinstance(body, dict) and body.get("status") == "error":
        code = body.get("code")
        message = body.get("message", "")
        if code == 400 and "No data is available" in message:
            return None
        raise TwelveDataError(f"Twelve Data API error {code}: {message}")

    response.raise_for_status()
    return body


def _format_time_bound(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _catalog_rows(session: Session, endpoint_config: TwelveDataEndpointConfig) -> Iterator[list[dict]]:
    body = _fetch(session, endpoint_config.path, dict(endpoint_config.params))
    rows = (body or {}).get(endpoint_config.data_key) or []
    for chunk_start in range(0, len(rows), CATALOG_CHUNK_SIZE):
        yield rows[chunk_start : chunk_start + CATALOG_CHUNK_SIZE]


def _symbol_rows(session: Session, endpoint_config: TwelveDataEndpointConfig, symbol: str) -> list[dict]:
    """One-shot per-symbol endpoints (quote, dividends, splits, earnings)."""
    params = {"symbol": symbol, **endpoint_config.params}
    body = _fetch(session, endpoint_config.path, params)
    if not body:
        return []

    if endpoint_config.data_key is None:
        row = {key: value for key, value in body.items() if key != "status"}
        return [row] if row else []

    meta = body.get("meta") or {}
    rows = body.get(endpoint_config.data_key) or []
    return [{"symbol": meta.get("symbol", symbol), **row} for row in rows]


def _time_series_pages(
    session: Session,
    symbol: str,
    interval: str,
    start_date: str | None,
    seeded_end_date: str | None,
    logger: FilteringBoundLogger,
) -> Iterator[tuple[list[dict], str | None]]:
    """Walk a symbol's bars from newest to oldest, yielding ``(rows, next_end_date)`` per page.

    ``outputsize`` always selects the most recent rows inside the date window regardless of the
    requested order (verified against the live API), so history deeper than one page is reached by
    moving ``end_date`` back to the oldest bar received. Without a lower bound (no ``start_date``)
    only the most recent page is fetched, keeping first syncs bounded on high-frequency intervals.
    The walk is additionally capped at ``MAX_TIME_SERIES_PAGES_PER_SYMBOL`` pages per run so an
    arbitrarily old start date on a minute interval can't occupy a worker with unbounded requests.
    """
    end_date = seeded_end_date
    # Oldest datetime already yielded — end_date is inclusive, so the boundary bar comes back on
    # the next page and must be dropped to avoid duplicate rows within one sync.
    boundary = seeded_end_date
    pages_fetched = 0

    while True:
        if pages_fetched >= MAX_TIME_SERIES_PAGES_PER_SYMBOL:
            logger.warning(
                "Twelve Data: time_series page cap reached, stopping history walk",
                symbol=symbol,
                interval=interval,
                start_date=start_date,
                pages_fetched=pages_fetched,
            )
            return
        params: dict[str, Any] = {
            "symbol": symbol,
            "interval": interval,
            "outputsize": TIME_SERIES_PAGE_SIZE,
            "order": "DESC",
        }
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        body = _fetch(session, "/time_series", params)
        pages_fetched += 1
        if body is None:
            return

        meta = body.get("meta") or {}
        values = body.get("values") or []
        full_page = len(values) >= TIME_SERIES_PAGE_SIZE
        # Bar datetimes are unique per symbol+interval and lexicographically ordered in the API's
        # own string format, so a string comparison is safe here.
        if boundary is not None:
            values = [value for value in values if value.get("datetime", "") < boundary]
        if not values:
            return

        oldest = values[-1].get("datetime")
        rows = [{"symbol": meta.get("symbol", symbol), "interval": interval, **value} for value in values]

        has_more = full_page and start_date is not None and oldest is not None
        yield rows, (oldest if has_more else None)

        if not has_more:
            return
        boundary = oldest
        end_date = oldest


def twelve_data_rows(
    api_key: str,
    endpoint: str,
    symbols: list[str],
    interval: str,
    config_start_date: str | None,
    resumable_source_manager: ResumableSourceManager[TwelveDataResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> Iterator[list[dict]]:
    endpoint_config = ENDPOINTS[endpoint]
    session = _make_session(api_key)

    if not endpoint_config.per_symbol:
        yield from _catalog_rows(session, endpoint_config)
        return

    # Re-checked at sync time (not just config validation) so a previously stored config can't
    # bypass the fan-out cap.
    if len(symbols) > MAX_SYMBOLS:
        raise TwelveDataError(
            f"Twelve Data symbol limit exceeded: {len(symbols)} symbols configured, maximum is {MAX_SYMBOLS}"
        )

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    completed = [s for s in (resume.completed_symbols if resume else []) if s in symbols]
    resume_symbol = resume.current_symbol if resume else None
    resume_end_date = resume.next_end_date if resume else None
    if resume is not None:
        logger.debug(
            f"Twelve Data: resuming {endpoint} — {len(completed)} symbols done, "
            f"current_symbol={resume_symbol}, next_end_date={resume_end_date}"
        )

    start_date: str | None
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        start_date = _format_time_bound(db_incremental_field_last_value)
    else:
        start_date = config_start_date or None

    for symbol in symbols:
        if symbol in completed:
            continue

        if endpoint == TIME_SERIES_ENDPOINT:
            seeded_end_date = resume_end_date if symbol == resume_symbol else None
            for rows, next_end_date in _time_series_pages(
                session, symbol, interval, start_date, seeded_end_date, logger
            ):
                yield rows
                # Save AFTER yielding so a crash re-yields the last page instead of skipping it;
                # merge dedupes the overlap on the primary key.
                if next_end_date is not None:
                    resumable_source_manager.save_state(
                        TwelveDataResumeConfig(
                            completed_symbols=completed, current_symbol=symbol, next_end_date=next_end_date
                        )
                    )
        else:
            rows = _symbol_rows(session, endpoint_config, symbol)
            if rows:
                yield rows

        completed = [*completed, symbol]
        resumable_source_manager.save_state(TwelveDataResumeConfig(completed_symbols=completed))


def twelve_data_source(
    api_key: str,
    endpoint: str,
    symbols: list[str],
    interval: str,
    config_start_date: str | None,
    resumable_source_manager: ResumableSourceManager[TwelveDataResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = ENDPOINTS[endpoint]
    is_time_series = endpoint == TIME_SERIES_ENDPOINT

    return SourceResponse(
        name=endpoint,
        items=lambda: twelve_data_rows(
            api_key=api_key,
            endpoint=endpoint,
            symbols=symbols,
            interval=interval,
            config_start_date=config_start_date,
            resumable_source_manager=resumable_source_manager,
            logger=logger,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Time series history is walked newest → oldest, so the incremental watermark must only
        # persist once the whole run completes (desc semantics), like Stripe.
        sort_mode="desc" if is_time_series else "asc",
        partition_count=1 if endpoint_config.partition_key else None,
        partition_size=1 if endpoint_config.partition_key else None,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Cheap token probe — /api_usage responds for every plan and costs no API credits."""
    session = _make_session(api_key)
    try:
        _fetch(session, "/api_usage", {})
    except TwelveDataError as e:
        return False, str(e)
    except Exception:
        return False, "Could not connect to Twelve Data"
    return True, None
