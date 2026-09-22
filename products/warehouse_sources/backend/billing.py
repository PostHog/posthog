"""Bills warehouse rows synced.

Two meters split the same set of completed jobs. `rows_synced` is what a customer pays
for; `free_historical_rows_synced` is the rest, currently a source's first week of
syncing. The nightly report aggregates them over a period, the quota meter in
`row_tracking` counts the billable half against the billing cycle, and the realtime
collector classifies one job as it finishes.

All three read the rules from here, and `tests/test_billing.py` runs the period queries
and the per-job classifier over the same jobs to check they still agree.
"""

from datetime import UTC, datetime, timedelta

from django.db.models import F, Q, QuerySet, Sum

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob, billable_destination_multiplier
from products.warehouse_sources.backend.types import ExternalDataJobStatus

ROWS_SYNCED_USAGE_KEY = "warehouse_rows_synced"
FREE_HISTORICAL_ROWS_SYNCED_USAGE_KEY = "warehouse_free_historical_rows_synced"

# A source's first week of syncing is free, so its jobs bill on the free historical meter.
FREE_HISTORICAL_WINDOW = timedelta(days=7)

# Everything synced in this window was free, whatever the source's age.
FREE_PERIOD_START = datetime(2025, 10, 29, 0, 0, 0, tzinfo=UTC)
FREE_PERIOD_END = datetime(2025, 11, 6, 0, 0, 0, tzinfo=UTC)


def billed_usage_for_job(job: ExternalDataJob) -> tuple[str, int] | None:
    """The meter and row count one finished job bills, or None if it bills nothing.

    Reads `job.pipeline`, so select it in. The guards mirror the filters the period
    queries below apply: a job bills only when it completed, stayed billable, and moved
    rows.
    """
    if (
        job.status != ExternalDataJobStatus.COMPLETED
        or not job.billable
        or not job.rows_synced
        or job.finished_at is None
    ):
        return None
    return _usage_key(job.finished_at, job.pipeline.created_at), job.rows_synced * max(1, len(job.destination_ids))


def _usage_key(finished_at: datetime, source_created_at: datetime) -> str:
    # The period queries measure a source's age against the period end; this measures it
    # against the job's own finish, the same way the quota meter in `row_tracking` does.
    # The two disagree only for a source created in the up-to-24h band around the seven-day
    # mark, which the report resolves in the customer's favour.
    if FREE_PERIOD_START <= finished_at < FREE_PERIOD_END:
        return FREE_HISTORICAL_ROWS_SYNCED_USAGE_KEY
    if source_created_at >= finished_at - FREE_HISTORICAL_WINDOW:
        return FREE_HISTORICAL_ROWS_SYNCED_USAGE_KEY
    return ROWS_SYNCED_USAGE_KEY


def _completed_billable_jobs(begin: datetime, end: datetime) -> QuerySet[ExternalDataJob]:
    return ExternalDataJob.objects.filter(
        finished_at__gte=begin,
        finished_at__lte=end,
        billable=True,
        status=ExternalDataJobStatus.COMPLETED,
    )


def _by_team(jobs: QuerySet[ExternalDataJob]) -> list:
    return list(jobs.values("team_id").annotate(total=Sum(F("rows_synced") * billable_destination_multiplier())))


def get_rows_synced_by_team(begin: datetime, end: datetime) -> list:
    if FREE_PERIOD_START <= begin < FREE_PERIOD_END:
        return []

    jobs = _completed_billable_jobs(begin, end)
    if begin >= FREE_PERIOD_END:
        jobs = jobs.filter(~Q(pipeline__created_at__gte=end - FREE_HISTORICAL_WINDOW))
    return _by_team(jobs)


def get_free_historical_rows_synced_by_team(begin: datetime, end: datetime) -> list:
    jobs = _completed_billable_jobs(begin, end)
    if not (FREE_PERIOD_START <= begin < FREE_PERIOD_END):
        jobs = jobs.filter(pipeline__created_at__gte=end - FREE_HISTORICAL_WINDOW)
    return _by_team(jobs)
