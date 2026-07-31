"""Day-by-day timeseries backfill for experiment metrics.

Computes one ExperimentMetricResult row per experiment day by running the experiment
query with as_of pinned to each day's end. Normally invoked via the Temporal
`experiment-timeseries-recalculation-workflow` activity, but has no Temporal
dependencies, so it can also run in-process (e.g. from demo data seeding).
"""

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import structlog

from posthog.schema import ExperimentQuery

from posthog.clickhouse.client.connection import Workload

from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.models.experiment import ExperimentMetricResult, ExperimentTimeseriesRecalculation
from products.experiments.backend.temporal.metric_resolution import build_metric

logger = structlog.get_logger(__name__)


def backfill_experiment_timeseries(recalculation_id: str, *, backfill_until: date | None = None) -> dict[str, Any]:
    """Backfill daily metric results for the recalculation request.

    `backfill_until` caps the backfill window. A running experiment (no end_date) otherwise
    backfills through the real today — callers whose data ends earlier (e.g. demo seeding
    pinned to a simulated clock) must pass the last date that actually has data, or every
    day in between costs a ClickHouse query that computes an empty result.
    """
    logger.info("Starting timeseries recalculation", recalculation_id=recalculation_id)

    try:
        recalculation_request = ExperimentTimeseriesRecalculation.objects.get(id=recalculation_id)
    except ExperimentTimeseriesRecalculation.DoesNotExist:
        raise ValueError(f"Recalculation request {recalculation_id} not found")

    if recalculation_request.status in (
        ExperimentTimeseriesRecalculation.Status.PENDING,
        ExperimentTimeseriesRecalculation.Status.FAILED,
    ):
        recalculation_request.status = ExperimentTimeseriesRecalculation.Status.IN_PROGRESS
        recalculation_request.save(update_fields=["status"])

    experiment = recalculation_request.experiment
    if not experiment.start_date:
        raise ValueError(f"Experiment {experiment.id} has no start_date")

    team_tz = ZoneInfo(experiment.team.timezone) if experiment.team.timezone else ZoneInfo("UTC")
    start_date = experiment.start_date.astimezone(team_tz).date()

    if experiment.end_date:
        end_date = experiment.end_date.astimezone(team_tz).date()
    else:
        end_date = datetime.now(team_tz).date()

    if backfill_until is not None:
        end_date = min(end_date, backfill_until)

    if recalculation_request.last_successful_date:
        current_date = recalculation_request.last_successful_date + timedelta(days=1)
        logger.info("Resuming recalculation", current_date=str(current_date))
    else:
        current_date = start_date
        logger.info("Starting fresh recalculation", current_date=str(current_date))

    metric_obj = build_metric(recalculation_request.metric)
    experiment_query = ExperimentQuery(experiment_id=experiment.id, metric=metric_obj)
    fingerprint = recalculation_request.fingerprint

    days_processed = 0

    while current_date <= end_date:
        try:
            end_of_day_team_tz = datetime.combine(current_date + timedelta(days=1), time(0, 0, 0)).replace(
                tzinfo=team_tz
            )
            query_to_utc = end_of_day_team_tz.astimezone(ZoneInfo("UTC"))

            query_runner = ExperimentQueryRunner(
                query=experiment_query,
                team=experiment.team,
                as_of=query_to_utc,
                workload=Workload.OFFLINE,
                # Scheduled backfill has no request user. Attribute the query to the experiment's creator
                # so warehouse HogQL access control is enforced.
                user=experiment.created_by,
                # Backfilling historical points is not user-visible pain — no terminal error event.
                error_event_context=None,
            )
            result = query_runner._calculate()

            ExperimentMetricResult.objects.update_or_create(
                experiment_id=experiment.id,
                metric_uuid=recalculation_request.metric["uuid"],
                query_to=query_to_utc,
                defaults={
                    "fingerprint": fingerprint,
                    "query_from": experiment.start_date,
                    "status": ExperimentMetricResult.Status.COMPLETED,
                    "result": result.model_dump(),
                    "query_id": None,
                    "completed_at": datetime.now(ZoneInfo("UTC")),
                    "error_message": None,
                },
            )

            recalculation_request.last_successful_date = current_date
            recalculation_request.save(update_fields=["last_successful_date"])
            days_processed += 1

        except Exception:
            logger.exception(
                "Timeseries recalculation failed",
                recalculation_id=recalculation_id,
                failed_date=str(current_date),
            )
            recalculation_request.status = ExperimentTimeseriesRecalculation.Status.FAILED
            recalculation_request.save(update_fields=["status"])
            raise

        current_date += timedelta(days=1)

    recalculation_request.status = ExperimentTimeseriesRecalculation.Status.COMPLETED
    recalculation_request.save(update_fields=["status"])

    logger.info(
        "Timeseries recalculation completed",
        recalculation_id=recalculation_id,
        days_processed=days_processed,
    )

    return {
        "recalculation_id": str(recalculation_id),
        "experiment_id": experiment.id,
        "metric_uuid": recalculation_request.metric["uuid"],
        "days_processed": days_processed,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }
