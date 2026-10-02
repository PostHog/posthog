"""The rolling window the stored CI views keep.

A rebuild reads every row it stores, so its cost follows the days kept. The views keep what a page
range of ``MAX_STORED_RANGE`` needs, and a longer range reads the raw tables.
"""

from datetime import timedelta

from products.engineering_analytics.backend.logic.delivery_scope import CI_LOOKBACK

MAX_STORED_RANGE = timedelta(days=30)

# A read reaches one more span before its range: a timeline reads the CI of the CI_LOOKBACK before it,
# and a comparison reads the previous period of the same length. The margin keeps a table that was
# built before midnight valid for a read after it.
STORED_RUNS_WINDOW = MAX_STORED_RANGE + max(MAX_STORED_RANGE, CI_LOOKBACK) + timedelta(days=3)

# A re-run keeps the jobs of its earlier attempts, which were created before the run's newest start, so
# a read that windows the run floors the jobs a week lower (see ``queries/_workflow_filters``).
STORED_JOBS_WINDOW = STORED_RUNS_WINDOW + timedelta(days=7)


def raw_date_floor(window: timedelta) -> str:
    """SQL for the date ``window`` ago as a date-only string, to compare against the raw ISO strings
    the source lands. It sits one day lower, so a timezone offset cannot cut a row inside the window."""
    return f"toString(toDate(now() - INTERVAL {window.days + 1} DAY))"
