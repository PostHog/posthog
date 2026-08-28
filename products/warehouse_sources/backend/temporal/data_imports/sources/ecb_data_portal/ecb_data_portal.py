import csv
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import requests
from dateutil import parser as dateutil_parser

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.ecb_data_portal.settings import (
    BASE_URL,
    ENDPOINT_CONFIGS,
)

# ECB's WAF returns a 400 HTML "security concerns" page instead of a normal SDMX error body for
# certain query shapes (verified live: a startPeriod set beyond the current date triggers it, even
# though it's syntactically valid). Never send a future date and treat this as non-retryable —
# retrying the same request just gets blocked again.
WAF_BLOCK_MARKER = "Your access has been blocked due to security concerns"


@frozen
class ECBResumeConfig:
    next_start_period: str


def _today() -> date:
    return datetime.now(UTC).date()


def _coerce_start_period(value: Any) -> Optional[date]:
    """Normalize a stored incremental/resume value (date, datetime, or string) to a date.

    ICP's TIME_PERIOD values are month-only ("2025-12"). dateutil.parser.parse fills any field
    missing from the string from its `default` argument, which defaults to *today* — silently
    swapping in today's day-of-month for a month-only string. Pinning `default` to a fixed
    anchor (day 1) makes the fallback deterministic instead of clock-dependent.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return dateutil_parser.parse(str(value), default=datetime(1, 1, 1)).date()
    except (ValueError, OverflowError):
        return None


@frozen
class _DateWindow:
    """One request window. Both ends are dates, so named fields keep a call site from
    reading them in the wrong order."""

    start: Optional[date]
    end: Optional[date]


def _daterange_chunks(start: Optional[date], end: date, chunk_years: Optional[int]) -> Iterator[_DateWindow]:
    """Split [start, end] into ascending chunk_years-sized windows.

    chunk_years=None (or no start date to anchor from) yields a single window that ends at
    None — the vendor returns all remaining history in one response, which is fine for
    small flows.
    """
    if chunk_years is None or start is None:
        yield _DateWindow(start=start, end=None)
        return

    cur = start
    while cur <= end:
        try:
            window_end = cur.replace(year=cur.year + chunk_years) - timedelta(days=1)
        except ValueError:
            # Anchor date is Feb 29 and cur.year + chunk_years isn't a leap year.
            window_end = cur.replace(year=cur.year + chunk_years, day=28) - timedelta(days=1)
        chunk_end = min(window_end, end)
        yield _DateWindow(start=cur, end=chunk_end)
        cur = chunk_end + timedelta(days=1)


def _request_csv_rows(
    session: requests.Session,
    flow: str,
    key: str,
    start_period: Optional[date],
    end_period: Optional[date],
) -> list[dict[str, str]]:
    params: dict[str, str] = {"format": "csvdata"}
    if start_period is not None:
        params["startPeriod"] = start_period.isoformat()
    if end_period is not None:
        params["endPeriod"] = end_period.isoformat()

    response = session.get(f"{BASE_URL}/service/data/{flow}/{key}", params=params)

    if response.status_code == 404:
        # SDMX's documented way of saying "no observations match this window" — not an error.
        return []
    if response.status_code == 400 and WAF_BLOCK_MARKER in response.text:
        raise ValueError(f"{WAF_BLOCK_MARKER} (flow={flow}, key={key})")
    response.raise_for_status()

    lines = response.text.splitlines()
    if not lines:
        return []
    return list(csv.DictReader(lines))


def check_connection() -> tuple[bool, str | None]:
    try:
        response = make_tracked_session().get(
            f"{BASE_URL}/service/data/EXR/D.USD.EUR.SP00.A",
            params={"format": "csvdata", "lastNObservations": "1"},
        )
    except Exception as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None

    return False, f"ECB Data Portal is unreachable (status {response.status_code}). Try again later."


def ecb_data_portal_source(
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[ECBResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> SourceResponse:
    endpoint_config = ENDPOINT_CONFIGS[endpoint]

    resume_state = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_state is not None:
        start = _coerce_start_period(resume_state.next_start_period)
    elif should_use_incremental_field and db_incremental_field_last_value is not None:
        start = _coerce_start_period(db_incremental_field_last_value)
    else:
        start = endpoint_config.history_start

    today = _today()

    def _items() -> Iterator[dict[str, str]]:
        session = make_tracked_session()
        for window in _daterange_chunks(start, today, endpoint_config.chunk_years):
            rows = _request_csv_rows(session, endpoint_config.flow, endpoint_config.key, window.start, window.end)
            # Multi-series (wildcarded) responses are grouped per series, each ascending by
            # TIME_PERIOD within its own block — not globally ordered. Sort so the pipeline's
            # sort_mode="asc" checkpointing sees a genuinely ascending stream.
            rows.sort(key=lambda row: row.get("TIME_PERIOD", ""))
            yield from rows

            if window.end is not None and window.end < today:
                resumable_source_manager.save_state(
                    ECBResumeConfig(next_start_period=(window.end + timedelta(days=1)).isoformat())
                )
            else:
                resumable_source_manager.clear_state()

    return SourceResponse(
        name=endpoint,
        items=_items,
        primary_keys=["KEY", "TIME_PERIOD"],
        sort_mode="asc",
        partition_keys=["TIME_PERIOD"],
        partition_mode="datetime",
        partition_format="month",
    )
