"""The rows one incremental materialization reads: the rows created at or after the run's window
start. The window start reaches the view as the ``{incremental_window_start}`` placeholder, which
data modeling binds to the key's watermark minus the lookback on an incremental run and to NULL on
a full build. A full build then seeds the rows created in the last ``SEED_LOOKBACK``, because it
has to fit in one ClickHouse query and a busy repository's whole job history does not. Coverage
grows forward from the seed with every incremental run, and a read that reaches back before it
(``MaterializedCI.covers``) uses the raw tables instead.

The floors compare the raw ISO-8601 ``created_at`` strings with the window start formatted the
same way, which is the one comparison that lets a warehouse scan skip files; the filter data
modeling injects on the parsed ``created_at`` cannot. Another row can change what a stored row
says: an earlier attempt shows that a job row is a re-listed copy, and the hand-off a Depot
workflow took decides whether a GitHub run is a shell. A scan for such rows reaches
``JOB_FLOOR_SLACK_ON_RUN_STARTED`` before the window.
"""

from datetime import timedelta

from products.engineering_analytics.backend.logic.queries._workflow_filters import JOB_FLOOR_SLACK_ON_RUN_STARTED

WINDOW_START = "{incremental_window_start}"
SEED_LOOKBACK = timedelta(days=30)


def stored_rows(column: str = "created_at") -> str:
    """The rows the run stores."""
    return f"{column} >= {_floor(days_before=0)}"


def stored_rows_and_earlier(column: str = "created_at") -> str:
    """The rows the run stores and the rows up to the slack before them."""
    return f"{column} >= {_floor(days_before=JOB_FLOOR_SLACK_ON_RUN_STARTED.days)}"


def _floor(*, days_before: int) -> str:
    seed_start = f"toTimeZone(now(), 'UTC') - INTERVAL {SEED_LOOKBACK.days} DAY"
    start = f"ifNull(toTimeZone({WINDOW_START}, 'UTC'), {seed_start})"
    if days_before:
        start = f"{start} - INTERVAL {days_before} DAY"
    # A fractional timestamp sorts before the same second's trailing Z, so use the second's prefix.
    return f"formatDateTime({start}, '%Y-%m-%dT%H:%i:%S')"
