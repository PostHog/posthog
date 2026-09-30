"""Assemble a completed metrics recalculation from the timeseries points of one scheduled run.

The scheduled timeseries workflows stamp each metric's query_to at the moment its own activity runs, so the points of
one run land seconds to minutes apart and never share an exact window. This module accepts that approximation: every
metric whose newest completed point falls inside the run qualifies, and the copies land under one shared query_to so
the recalculation reads (`get_run_results`, derived counters, the metric-config-change window reuse) work unchanged.

Two workflows (inline metrics, saved metrics) run per hour and each calls this for the same experiment with its own
run start. The row belongs to one scheduled run of the experiment, not to one workflow: the first pass creates it,
and a later pass in the same hour adds the copies the row still lacks. The lookup is scoped to the run's start, so a
team with a second recalculation time later in the day gets a fresh row for that run.
"""

from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

import structlog

from posthog.models.scoping import team_scope

from products.experiments.backend.metric_calculation.results import MetricResultStore
from products.experiments.backend.metric_calculation.spec import CalculationSpec, plan
from products.experiments.backend.metric_resolution import is_daily_timeseries_metric
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentMetricsRecalculation,
)
from products.experiments.backend.recalculation import get_active_recalculation

logger = structlog.get_logger(__name__)

# The two hourly workflows start within the same cron minute; yesterday's sync row is a day older.
_SAME_RUN_LOOKBACK = timedelta(hours=1)


def sync_timeseries_recalculation(
    experiment_id: int, *, team_id: int, run_started_at: datetime, now: datetime | None = None
) -> str | None:
    """Copy the timeseries points written between run_started_at and now into this run's recalculation.

    Returns the recalculation id when a row was created or gained copies, else None: no metric has a point
    inside the run, the run's sync row already holds every point, or another run's window already reaches the
    oldest qualifying point. A supported metric without a point is counted in total_metrics but gets no copy, so
    the frontend sees the gap and heals it. Metric types the scheduled run cannot compute are left out of the row.
    """
    now = now or timezone.now()
    with team_scope(team_id, canonical=True), transaction.atomic():
        try:
            # Same lock as request_recalculation and the calc result write; the two hourly workflows serialize
            # here so they see each other's row and share it instead of creating two. Taken on the initial read
            # so the metric config inspected below cannot go stale while waiting for the lock.
            experiment = Experiment.objects.select_for_update(no_key=True).get(
                id=experiment_id, team_id=team_id, deleted=False
            )
        except Experiment.DoesNotExist:
            return None
        if experiment.start_date is None:
            return None

        store = MetricResultStore(experiment_id=experiment.id)
        metric_uuids: list[str] = []
        points: dict[str, tuple[CalculationSpec, ExperimentMetricResult]] = {}
        for spec in plan(experiment):
            if not is_daily_timeseries_metric(spec.definition):
                continue
            metric_uuids.append(spec.metric_id)
            row = store.latest_daily_point(spec, since=run_started_at, until=now)
            if row is not None:
                points[spec.metric_id] = (spec, row)

        if not points:
            return None

        oldest_point = min(row.query_to for _, row in points.values())
        newest_point = max(row.query_to for _, row in points.values())

        recalculation = (
            ExperimentMetricsRecalculation.objects.filter(
                experiment=experiment,
                trigger=ExperimentMetricsRecalculation.Trigger.TIMESERIES_SYNC,
                query_to__gte=run_started_at - _SAME_RUN_LOOKBACK,
            )
            .order_by("-query_to")
            .first()
        )
        if recalculation is not None and recalculation.query_to is not None:
            already_copied = store.metric_uuids_stored_at(recalculation.query_to, points.keys())
            missing = {uuid: point for uuid, point in points.items() if uuid not in already_copied}
            if not missing:
                return None
            store.copy_into_sync_run(
                recalculation.query_to, missing.values(), query_from=experiment.start_date, completed_at=now
            )
            copied = len(missing)
        else:
            # A run that already reaches the oldest point covers this data. Trigger-failure tombstones never got
            # a window and are ignored. An active run has no window until its start activity stamps one, and
            # it would finish behind a sync row created now, so it counts as coverage too.
            already_covered = (
                ExperimentMetricsRecalculation.objects.filter(experiment=experiment, query_to__gte=oldest_point)
                .exclude(Q(status=ExperimentMetricsRecalculation.Status.FAILED) & Q(completed_at__isnull=True))
                .exists()
            )
            if already_covered or get_active_recalculation(experiment) is not None:
                return None

            window = MetricResultStore.sync_copy_window(newest_point)
            recalculation = ExperimentMetricsRecalculation.objects.create(
                team=experiment.team,
                experiment=experiment,
                status=ExperimentMetricsRecalculation.Status.COMPLETED,
                trigger=ExperimentMetricsRecalculation.Trigger.TIMESERIES_SYNC,
                query_to=window,
                started_at=now,
                completed_at=now,
                total_metrics=len(metric_uuids),
                metric_uuids=metric_uuids,
            )
            store.copy_into_sync_run(window, points.values(), query_from=experiment.start_date, completed_at=now)
            copied = len(points)

    logger.info(
        "Synced timeseries points into a metrics recalculation",
        experiment_id=experiment_id,
        recalculation_id=str(recalculation.id),
        copied_metrics=copied,
        total_metrics=len(metric_uuids),
    )
    return str(recalculation.id)
