"""Scan floors for the stored CI views. Data modeling binds ``{incremental_window_start}`` to the
watermark minus the lookback on an incremental run, and to NULL on a full build. The floors compare
raw ISO-8601 strings, because a predicate on a parsed timestamp cannot let a warehouse scan skip files.
"""

from products.engineering_analytics.backend.logic._shared import DEFAULT_WINDOW
from products.engineering_analytics.backend.logic.queries._workflow_filters import (
    JOB_FLOOR_SLACK_ON_RUN_STARTED,
    WIDEST_SCAN_FLOOR_SLACK,
)

WINDOW_START = "{incremental_window_start}"
# A full build runs as one ClickHouse query, which cannot read a busy repository's whole job
# history, so it seeds only this much. The slack keeps the scan floor of a default-window read
# inside the seed.
SEED_LOOKBACK = DEFAULT_WINDOW + WIDEST_SCAN_FLOOR_SLACK


def stored_rows(column: str = "created_at") -> str:
    """A predicate on the raw string ``column`` that keeps the rows the run stores."""
    return f"{column} >= {_floor(days_before=0)}"


def stored_rows_and_earlier(column: str = "created_at") -> str:
    """As ``stored_rows``, reaching ``JOB_FLOOR_SLACK_ON_RUN_STARTED`` earlier. An earlier row can
    decide what a stored row says: a first listing marks a job copy, and a hand-off marks a shell."""
    return f"{column} >= {_floor(days_before=JOB_FLOOR_SLACK_ON_RUN_STARTED.days)}"


def _floor(*, days_before: int) -> str:
    seed_start = f"toTimeZone(now(), 'UTC') - INTERVAL {SEED_LOOKBACK.days} DAY"
    start = f"ifNull(toTimeZone({WINDOW_START}, 'UTC'), {seed_start})"
    if days_before:
        start = f"{start} - INTERVAL {days_before} DAY"
    # A fractional timestamp sorts before the same second's trailing Z, so use the second's prefix.
    return f"formatDateTime({start}, '%Y-%m-%dT%H:%i:%S')"
