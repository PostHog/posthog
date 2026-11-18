"""How many retries one import run may spend, and how often a failing schema may run at all.

It lives apart from `external_data_job` so the schema model can read it: that module loads
temporalio, and the model loads during django.setup().
"""

import datetime as dt

# The largest retry cap an import activity gets.
MAX_RESUMABLE_SOURCE_RETRIES_PRODUCTION = 20

# Consecutive failed runs after which a schema stops getting the full retry cap. Of the schemas
# that completed at least one run in a week of production, 96% of their failure streaks ended
# within four runs, so a streak this long means a broken source rather than a flapping one.
GIVE_UP_AFTER_FAILED_RUNS = 5

# Two rather than one so a single worker restart cannot be the reason a run fails.
FAILING_SCHEMA_MAX_IMPORT_ATTEMPTS = 2

# Attempts an import on the resumable cap may spend before it has committed anything to resume
# from. Above the per-run non-retryable allowance of four attempts, so an error a source
# classifies as non-retryable still gives up first and keeps its own message.
PROGRESSLESS_RESUMABLE_ATTEMPTS = 4

# The smallest gap between two runs of a failing schema, and the cap that gap grows to. The cap
# bounds how stale a table gets once its source recovers.
FAILING_SCHEMA_RUN_GAP_BASE = dt.timedelta(minutes=10)
FAILING_SCHEMA_RUN_GAP_CAP = dt.timedelta(hours=1)


def import_retry_budget(budget: int, failed_runs_in_a_row: int) -> int:
    """`budget` for a healthy schema, cut to a floor once the streak says the source is broken."""
    if failed_runs_in_a_row < GIVE_UP_AFTER_FAILED_RUNS:
        return budget
    return min(budget, FAILING_SCHEMA_MAX_IMPORT_ATTEMPTS)


def min_gap_between_runs(failed_runs_in_a_row: int) -> dt.timedelta | None:
    """How long after its last failure a schema may run again, or None while it is not in a streak.

    The gap doubles per failed run past the threshold, so a source that recovers on its own loses
    at most one cap-length window, while one that never recovers settles at the cap.
    """
    if failed_runs_in_a_row < GIVE_UP_AFTER_FAILED_RUNS:
        return None
    doublings = failed_runs_in_a_row - GIVE_UP_AFTER_FAILED_RUNS
    # Bounded before the shift so a long-dead schema cannot build an overflowing timedelta.
    if doublings >= 32:
        return FAILING_SCHEMA_RUN_GAP_CAP
    return min(FAILING_SCHEMA_RUN_GAP_BASE * (2**doublings), FAILING_SCHEMA_RUN_GAP_CAP)
