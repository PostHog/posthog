"""
How long the daily calculation covers an experiment. The daily time series job, the scheduled recalculation and the
stale experiment health check all read this module, so they agree on which experiments the daily calculation covers.
`EXPERIMENT_RECALCULATION_MAX_AGE_DAYS` in products/experiments/frontend/constants.ts copies the number.
"""

from datetime import datetime, timedelta

DAILY_CALCULATION_DAYS = 60


def daily_calculation_start_cutoff(now: datetime) -> datetime:
    """The earliest start date that the daily calculation covers at `now`."""
    return now - timedelta(days=DAILY_CALCULATION_DAYS)


def daily_calculation_end(start_date: datetime | None) -> datetime | None:
    """When the daily calculation stops covering an experiment with this start date."""
    return None if start_date is None else start_date + timedelta(days=DAILY_CALCULATION_DAYS)


def is_past_daily_calculation(start_date: datetime | None, now: datetime) -> bool:
    """Whether the daily calculation leaves out an experiment with this start date. The daily jobs keep the
    experiments with `start_date >= daily_calculation_start_cutoff(now)`, so this is the exact complement."""
    return start_date is not None and start_date < daily_calculation_start_cutoff(now)
