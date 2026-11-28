"""Start and finish of a recalculation run: the query window and the status transitions.

Per-metric progress is folded into the calculation step.
"""

from datetime import datetime

from django.db import close_old_connections
from django.db.models import Q
from django.utils import timezone

import structlog
from temporalio.exceptions import ApplicationError

from posthog.models.scoping import team_scope
from posthog.sync import database_sync_to_async_pool

from products.experiments.backend.hogql_queries.base_query_utils import experiment_window_end
from products.experiments.backend.models.experiment import Experiment, ExperimentMetricsRecalculation
from products.experiments.backend.recalculation.kill_switch import recalculation_enabled
from products.experiments.backend.temporal.models import RecalculationProgressUpdate

from . import analytics, run_state

logger = structlog.get_logger(__name__)


# Triggers that keep the prior window so unchanged metrics hit the (experiment, metric, query_to, fingerprint)
# cache and only new or changed metrics recompute. Every other trigger advances the window to now.
_REUSE_WINDOW_TRIGGERS = frozenset(
    {
        ExperimentMetricsRecalculation.Trigger.METRIC_CONFIG_CHANGE,
        ExperimentMetricsRecalculation.Trigger.MANUAL_RETRY,
        ExperimentMetricsRecalculation.Trigger.HEAL_LATEST_RUN,
    }
)


def _resolve_query_to(experiment: Experiment, trigger: str | None) -> datetime:
    """Window end for a starting run: reuse the latest terminal run's for metric-scoped changes, else advance.

    A stopped experiment has a fixed window (experiment_window_end always returns end_date), so reuse is moot
    and we skip the lookup. archived is orthogonal: it never affects the window, which reads only end_date.
    """
    now = timezone.now()
    if experiment.is_stopped or trigger not in _REUSE_WINDOW_TRIGGERS:
        return experiment_window_end(experiment, now)

    # Any terminal run is a valid anchor, not only COMPLETED: a partial-failure run is marked FAILED yet its
    # succeeded metrics hold result rows at that (newer) query_to. Mirror get_latest_recalculation so reuse
    # picks the newest real window instead of falling back to an older one and moving results backward.
    latest_query_to = (
        ExperimentMetricsRecalculation.objects.filter(experiment=experiment, query_to__isnull=False)
        .filter(
            Q(status=ExperimentMetricsRecalculation.Status.COMPLETED)
            | (Q(status=ExperimentMetricsRecalculation.Status.FAILED) & Q(completed_at__isnull=False))
        )
        .order_by("-query_to")
        .values_list("query_to", flat=True)
        .first()
    )
    if latest_query_to is None:
        return experiment_window_end(experiment, now)

    # A reset+relaunch leaves the prior run's rows behind with a query_to from before the new start_date.
    # Never reuse a cutoff below start_date, or the window would begin before the experiment exists.
    if experiment.start_date is not None and latest_query_to < experiment.start_date:
        return experiment_window_end(experiment, now)
    return experiment_window_end(experiment, latest_query_to)


@database_sync_to_async_pool
def _update_recalculation_progress_sync(update: RecalculationProgressUpdate) -> str | None:
    close_old_connections()

    if update.mark_started == update.mark_completed:
        # Contract: exactly one of mark_started / mark_completed per call. Both-true or neither-true is a
        # workflow bug — fail non-retryable so Temporal terminates promptly.
        raise ApplicationError(
            "RecalculationProgressUpdate must set exactly one of mark_started or mark_completed",
            type="invalid_input",
            non_retryable=True,
        )

    state = run_state._get_recalc_state(update.recalculation_id)
    with team_scope(state.team_id, canonical=True):
        # Start: write the data-window end + started_at + initial state under a first-write-wins guard so a
        # Temporal retry of this activity can't move query_to forward (which would orphan any rows persisted by
        # calc activities still in flight from the prior attempt).
        if update.mark_started:
            if not recalculation_enabled() and run_state._fail_pending_run(update.recalculation_id):
                raise run_state._recalculation_paused_error(update.recalculation_id)
            experiment = Experiment.objects.get(id=state.experiment_id)
            proposed_query_to = _resolve_query_to(experiment, state.trigger)

            won = (
                ExperimentMetricsRecalculation.objects.filter(
                    id=update.recalculation_id,
                    query_to__isnull=True,
                    status__in=[
                        ExperimentMetricsRecalculation.Status.PENDING,
                        ExperimentMetricsRecalculation.Status.IN_PROGRESS,
                    ],
                ).update(
                    query_to=proposed_query_to,
                    started_at=timezone.now(),
                    status=update.status or ExperimentMetricsRecalculation.Status.IN_PROGRESS,
                    total_metrics=update.total_metrics if update.total_metrics is not None else 0,
                    metric_uuids=update.metric_uuids if update.metric_uuids is not None else [],
                )
                == 1
            )

            if won:
                return proposed_query_to.isoformat()

            existing = (
                ExperimentMetricsRecalculation.objects.filter(id=update.recalculation_id)
                .values_list("query_to", "status")
                .first()
            )

            if existing is None:
                logger.warning("mark_started_rejected_row_missing", recalculation_id=update.recalculation_id)
                return None

            existing_query_to, existing_status = existing
            if existing_status not in (
                ExperimentMetricsRecalculation.Status.PENDING,
                ExperimentMetricsRecalculation.Status.IN_PROGRESS,
            ):
                logger.warning(
                    "mark_started_rejected_run_terminal",
                    recalculation_id=update.recalculation_id,
                    status=existing_status,
                )
                return None

            return existing_query_to.isoformat() if existing_query_to is not None else None

        # Finish: same first-write-wins guard so a retried mark_completed activity doesn't re-stamp the
        # completion timestamp (and, by symmetry with mark_started, doesn't reopen a closed run). The status
        # filter makes an out-of-band terminal write (staleness force-fail, admin action) authoritative even
        # when its completed_at is still NULL: the force-fail leaves completed_at unset and its workflow
        # cancel is best-effort, so without the filter a surviving workflow would overwrite the tombstone.
        won = (
            ExperimentMetricsRecalculation.objects.filter(
                id=update.recalculation_id,
                completed_at__isnull=True,
                status__in=[
                    ExperimentMetricsRecalculation.Status.PENDING,
                    ExperimentMetricsRecalculation.Status.IN_PROGRESS,
                ],
            ).update(
                completed_at=timezone.now(),
                status=update.status or ExperimentMetricsRecalculation.Status.COMPLETED,
                # The run is terminal, so no retry can be pending. Sweeps entries orphaned by a hard-killed
                # final attempt, which never reaches the activity-local cleanup branches.
                metric_retries={},
            )
            == 1
        )
        # Emit the run-level analytics event only on the winning (first) completion, so a retried
        # mark_completed doesn't double-count.
        if won:
            analytics._capture_results_refresh_completed(update)
        else:
            existing_finish_state = (
                ExperimentMetricsRecalculation.objects.filter(id=update.recalculation_id)
                .values_list("status", "completed_at")
                .first()
            )
            # completed_at set means a retried activity lost the normal dedupe race — silence. completed_at
            # NULL means the run was force-failed out-of-band while this workflow was still executing.
            if existing_finish_state is not None and existing_finish_state[1] is None:
                logger.warning(
                    "mark_completed_rejected_run_terminal",
                    recalculation_id=update.recalculation_id,
                    status=existing_finish_state[0],
                )
        return None
