"""Assemble a completed metrics recalculation from the timeseries points of one daily run.

The daily timeseries workflows stamp each metric's query_to at the moment its own activity runs, so the points of one
run land seconds to minutes apart and never share an exact window. This module accepts that approximation: every
metric whose newest completed point falls inside the run qualifies, and the copies land under one shared query_to so
the recalculation reads (`get_run_results`, derived counters, the metric-config-change window reuse) work unchanged.

Two workflows (inline metrics, saved metrics) run per hour and each calls this for the same experiment with its own
run start. The row belongs to the experiment's daily run, not to one workflow: the first pass creates it, and a later
pass adds the copies the row still lacks.
"""

from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

import structlog

from posthog.models.scoping import team_scope

from products.experiments.backend.hogql_queries.experiment_metric_fingerprint import compute_metric_fingerprint
from products.experiments.backend.hogql_queries.utils import get_experiment_stats_method
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentMetricsRecalculation,
)
from products.experiments.backend.recalculation import get_active_recalculation
from products.experiments.backend.temporal.metric_resolution import find_metric_dict, is_daily_timeseries_metric
from products.experiments.backend.temporal.recalc_fingerprint import compute_recalc_fingerprint
from products.experiments.backend.temporal.recalculation_logic import discover_experiment_metrics

logger = structlog.get_logger(__name__)

# The copies land one second past the newest point. A copy at a point's own query_to would share its
# (experiment, metric_uuid, query_to) key with the timeseries row and rewrite that row's fingerprint.
_WINDOW_OFFSET = timedelta(seconds=1)

# The two hourly workflows start within the same cron minute; yesterday's sync row is a day older.
_SAME_RUN_LOOKBACK = timedelta(hours=1)


def sync_timeseries_recalculation(
    experiment_id: int, *, team_id: int, run_started_at: datetime, now: datetime | None = None
) -> str | None:
    """Copy the timeseries points written between run_started_at and now into this daily run's recalculation.

    Returns the recalculation id when a row was created or gained copies, else None: no metric has a point
    inside the run, the day's sync row already holds every point, or another run's window already reaches the
    oldest qualifying point. A supported metric without a point is counted in total_metrics but gets no copy, so
    the frontend sees the gap and heals it. Metric types the daily run cannot compute are left out of the row.
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

        stats_method = get_experiment_stats_method(experiment)
        metric_uuids: list[str] = []
        points: dict[str, tuple[str, ExperimentMetricResult]] = {}
        for metric in discover_experiment_metrics(experiment):
            metric_dict = find_metric_dict(experiment, metric.metric_uuid)
            if metric_dict is None or not is_daily_timeseries_metric(metric_dict):
                continue
            metric_uuids.append(metric.metric_uuid)
            config_fp = compute_metric_fingerprint(
                metric_dict,
                experiment.start_date,
                stats_method,
                experiment.exposure_criteria,
                only_count_matured_users=experiment.only_count_matured_users,
                excluded_variants=experiment.excluded_variants,
            )
            row = (
                ExperimentMetricResult.objects.filter(
                    experiment=experiment,
                    metric_uuid=metric.metric_uuid,
                    fingerprint=config_fp,
                    status=ExperimentMetricResult.Status.COMPLETED,
                    query_to__gte=run_started_at,
                    query_to__lte=now,
                )
                .order_by("-query_to")
                .first()
            )
            if row is not None:
                points[metric.metric_uuid] = (compute_recalc_fingerprint(config_fp), row)

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
            already_copied = set(
                ExperimentMetricResult.objects.filter(
                    experiment=experiment, query_to=recalculation.query_to, metric_uuid__in=points.keys()
                ).values_list("metric_uuid", flat=True)
            )
            missing = {uuid: point for uuid, point in points.items() if uuid not in already_copied}
            if not missing:
                return None
            _copy_points(experiment, recalculation.query_to, missing, now)
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

            recalculation = ExperimentMetricsRecalculation.objects.create(
                team=experiment.team,
                experiment=experiment,
                status=ExperimentMetricsRecalculation.Status.COMPLETED,
                trigger=ExperimentMetricsRecalculation.Trigger.TIMESERIES_SYNC,
                query_to=newest_point + _WINDOW_OFFSET,
                started_at=now,
                completed_at=now,
                total_metrics=len(metric_uuids),
                metric_uuids=metric_uuids,
            )
            _copy_points(experiment, newest_point + _WINDOW_OFFSET, points, now)
            copied = len(points)

    logger.info(
        "Synced timeseries points into a metrics recalculation",
        experiment_id=experiment_id,
        recalculation_id=str(recalculation.id),
        copied_metrics=copied,
        total_metrics=len(metric_uuids),
    )
    return str(recalculation.id)


def _copy_points(
    experiment: Experiment,
    window: datetime,
    points: dict[str, tuple[str, ExperimentMetricResult]],
    now: datetime,
) -> None:
    for metric_uuid, (recalc_fp, row) in points.items():
        ExperimentMetricResult.objects.update_or_create(
            experiment=experiment,
            metric_uuid=metric_uuid,
            query_to=window,
            defaults={
                "fingerprint": recalc_fp,
                "query_from": experiment.start_date,
                "status": ExperimentMetricResult.Status.COMPLETED,
                "result": row.result,
                "query_id": None,
                "completed_at": now,
                "error_message": None,
            },
        )
