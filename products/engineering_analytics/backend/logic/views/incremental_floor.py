"""The rows one incremental materialization reads: the rows created at or after the run's window
start. The window start reaches the view as the ``{incremental_window_start}`` placeholder, which
data modeling binds to the key's watermark minus the lookback on an incremental run and to NULL on
a full build, so the floor then keeps every row.

The floors compare the raw ISO-8601 ``created_at`` strings with the window start formatted the
same way, which is the one comparison that lets a warehouse scan skip files; the filter data
modeling injects on the parsed ``created_at`` cannot. Another row can change what a stored row
says: an earlier attempt shows that a job row is a re-listed copy, and the hand-off a Depot
workflow took decides whether a GitHub run is a shell. A scan for such rows reaches
``JOB_FLOOR_SLACK_ON_RUN_STARTED`` before the window.
"""

from products.engineering_analytics.backend.logic.queries._workflow_filters import JOB_FLOOR_SLACK_ON_RUN_STARTED

WINDOW_START = "{incremental_window_start}"


def stored_rows(column: str = "created_at") -> str:
    """The rows the run stores."""
    return f"{column} >= {_floor(days_before=0)}"


def stored_rows_and_earlier(column: str = "created_at") -> str:
    """The rows the run stores and the rows up to the slack before them."""
    return f"{column} >= {_floor(days_before=JOB_FLOOR_SLACK_ON_RUN_STARTED.days)}"


def _floor(*, days_before: int) -> str:
    start = f"toTimeZone({WINDOW_START}, 'UTC')"
    if days_before:
        start = f"{start} - INTERVAL {days_before} DAY"
    return f"ifNull(formatDateTime({start}, '%Y-%m-%dT%H:%M:%SZ'), '')"
