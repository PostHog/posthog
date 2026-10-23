"""Day-by-day timeseries backfill for experiment metrics.

Computes one ExperimentMetricResult row per experiment day by running the experiment
query with as_of pinned to each day's end. Normally invoked via the Temporal
`experiment-timeseries-recalculation-workflow` activity, but has no Temporal
dependencies, so it can also run in-process (e.g. from demo data seeding).
"""

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.db import transaction

import structlog

from posthog.schema import ExperimentQuery

from posthog.clickhouse.client.connection import Workload

from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.hogql_queries.utils import sanitize_non_finite
from products.experiments.backend.metric_calculation.config import find_calculation_config_by_key
from products.experiments.backend.metric_calculation.results import MetricResultStore
from products.experiments.backend.metric_resolution import build_metric
from products.experiments.backend.models.experiment import Experiment, ExperimentTimeseriesRecalculation

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

    ExperimentTimeseriesRecalculation.objects.filter(
        id=recalculation_id,
        status__in=[ExperimentTimeseriesRecalculation.Status.PENDING, ExperimentTimeseriesRecalculation.Status.FAILED],
    ).update(status=ExperimentTimeseriesRecalculation.Status.IN_PROGRESS)
    recalculation_request.refresh_from_db()

    if recalculation_request.status in (
        ExperimentTimeseriesRecalculation.Status.CANCELED,
        ExperimentTimeseriesRecalculation.Status.COMPLETED,
    ):
        return {
            "recalculation_id": str(recalculation_request.id),
            "days_processed": 0,
            "status": recalculation_request.status,
        }

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
    calculation_config = find_calculation_config_by_key(
        experiment, recalculation_request.metric.get("uuid") or "", fingerprint
    )
    results = MetricResultStore(experiment_id=experiment.id)

    days_processed = 0
    if calculation_config is None:
        ExperimentTimeseriesRecalculation.objects.filter(id=recalculation_id).update(
            status=ExperimentTimeseriesRecalculation.Status.CANCELED
        )
        return {"recalculation_id": str(recalculation_request.id), "days_processed": 0, "status": "canceled"}

    while current_date <= end_date:
        try:
            end_of_day_team_tz = datetime.combine(current_date + timedelta(days=1), time(0, 0, 0)).replace(
                tzinfo=team_tz
            )
            query_to_utc = end_of_day_team_tz.astimezone(ZoneInfo("UTC"))

            experiment.team.refresh_from_db()
            query_runner = ExperimentQueryRunner(
                query=experiment_query,
                team=experiment.team,
                as_of=query_to_utc,
                workload=Workload.OFFLINE,
                # Userless background recompute. Warehouse access is enforced when the metric is authored,
                # so resolve warehouse tables here instead of failing closed.
                bypass_warehouse_access_control=True,
                # Backfilling historical points is not user-visible pain — no terminal error event.
                error_event_context=None,
            )
            runtime_config = query_runner.calculation_config.settings.build_metric_config(
                metric_id=calculation_config.metric_id,
                role=calculation_config.role,
                definition=recalculation_request.metric,
            )
            if runtime_config.calculation_key() != fingerprint:
                ExperimentTimeseriesRecalculation.objects.filter(id=recalculation_id).update(
                    status=ExperimentTimeseriesRecalculation.Status.CANCELED
                )
                break
            result = query_runner._calculate()

            with transaction.atomic():
                Experiment.objects.select_for_update(no_key=True).filter(
                    id=experiment.id, team_id=experiment.team_id
                ).exists()
                current_request = ExperimentTimeseriesRecalculation.objects.select_for_update().get(id=recalculation_id)
                if current_request.status != ExperimentTimeseriesRecalculation.Status.IN_PROGRESS:
                    break
                results.record_daily_point(
                    recalculation_request.metric["uuid"],
                    fingerprint,
                    calculation_config=calculation_config,
                    window=query_to_utc,
                    query_from=experiment.start_date,
                    result=sanitize_non_finite(result.model_dump()),
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
            ExperimentTimeseriesRecalculation.objects.filter(
                id=recalculation_id, status=ExperimentTimeseriesRecalculation.Status.IN_PROGRESS
            ).update(status=ExperimentTimeseriesRecalculation.Status.FAILED)
            raise

        current_date += timedelta(days=1)

    ExperimentTimeseriesRecalculation.objects.filter(
        id=recalculation_id, status=ExperimentTimeseriesRecalculation.Status.IN_PROGRESS
    ).update(status=ExperimentTimeseriesRecalculation.Status.COMPLETED)

    recalculation_request.refresh_from_db(fields=["status"])
    logger.info(
        "Timeseries recalculation finished",
        status=recalculation_request.status,
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
        "status": recalculation_request.status,
    }
