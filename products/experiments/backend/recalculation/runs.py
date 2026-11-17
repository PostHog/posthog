"""``get_latest_recalculation`` — most recent recalc row for an experiment, or ``None``."""

from datetime import timedelta
from uuid import UUID

from django.db.models import Q, QuerySet
from django.utils import timezone

from posthog.models.scoping import team_scope

from products.experiments.backend.models.experiment import Experiment, ExperimentMetricsRecalculation
from products.experiments.backend.temporal.recalculation.dispatch import workflow_may_still_run

# How long an active (PENDING/IN_PROGRESS) row blocks new recalculations. Beyond this, the row is treated as
# stale and a fresh recalc is allowed. An IN_PROGRESS row counts from started_at, so it must outlast the phase
# after the start activity: the calc budget (METRIC_CALC_SCHEDULE_TO_CLOSE_TIMEOUT_SECONDS), the failure
# backstop and the finish step. test_in_progress_phase_ends_before_the_staleness_ttl keeps that sum below this
# value, so a legitimately-slow run can finish without being clobbered. It is also tight enough that an operator
# can recover within an hour if the workflow never started (Temporal connect failure, transient infra issue,
# etc.). See the rollback in start_metrics_recalculation_workflow for the happy-path failure handling; this TTL
# is the defense-in-depth backstop if that rollback itself fails.
STALE_RECALC_THRESHOLD = timedelta(minutes=30)

# A calc that waits on the activity or precompute queue has no time budget, so a row past STALE_RECALC_THRESHOLD
# stays active while Temporal says its workflow may still run, up to this ceiling. Past it, the row is stale
# whatever Temporal says, so a stuck workflow or a Temporal outage cannot block an experiment for longer.
_QUEUED_RECALC_CEILING = timedelta(hours=1)


def active_recalculation_filter() -> Q:
    """The rows that block a new recalculation: PENDING or IN_PROGRESS, inside the staleness bound.

    The scheduled discovery applies the same filter to many experiments in one query. A row past the bound can
    still be active while its workflow may run (queued_recalculation); get_active_recalculation and the request
    path check that one experiment at a time.
    """
    threshold = timezone.now() - STALE_RECALC_THRESHOLD
    return Q(status=ExperimentMetricsRecalculation.Status.PENDING, created_at__gte=threshold) | Q(
        status=ExperimentMetricsRecalculation.Status.IN_PROGRESS, started_at__gte=threshold
    )


def get_active_recalculation(experiment: Experiment) -> ExperimentMetricsRecalculation | None:
    with team_scope(experiment.team_id, canonical=True):
        active = (
            ExperimentMetricsRecalculation.objects.filter(team=experiment.team, experiment=experiment)
            .filter(active_recalculation_filter())
            .order_by("-created_at")
            .first()
        )
        return active if active is not None else queued_recalculation(experiment)


def queued_recalculation(experiment: Experiment) -> ExperimentMetricsRecalculation | None:
    """An active row between STALE_RECALC_THRESHOLD and _QUEUED_RECALC_CEILING whose workflow may still run.

    Callers hold the team scope. It asks Temporal only when such a row exists.
    """
    threshold = timezone.now() - STALE_RECALC_THRESHOLD
    ceiling = timezone.now() - _QUEUED_RECALC_CEILING
    candidates = (
        ExperimentMetricsRecalculation.objects.filter(team=experiment.team, experiment=experiment)
        .filter(
            Q(
                status=ExperimentMetricsRecalculation.Status.PENDING,
                created_at__lt=threshold,
                created_at__gte=ceiling,
            )
            | Q(
                status=ExperimentMetricsRecalculation.Status.IN_PROGRESS,
                started_at__lt=threshold,
                started_at__gte=ceiling,
            )
        )
        .order_by("-created_at")
    )
    for candidate in candidates:
        if workflow_may_still_run(str(candidate.id)):
            return candidate
    return None


def terminal_recalculations(experiment: Experiment) -> QuerySet[ExperimentMetricsRecalculation]:
    """Runs that really finished. Callers hold the team scope.

    completed_at is only ever stamped by the workflow's finalize step, so it separates runs that really
    finished from trigger-failure tombstones (status flipped to FAILED at create time, never started). Keying
    on metric_errors instead would hide a failed run whose failures live only in result rows.
    """
    return ExperimentMetricsRecalculation.objects.filter(team=experiment.team, experiment=experiment).filter(
        Q(status=ExperimentMetricsRecalculation.Status.COMPLETED)
        | (Q(status=ExperimentMetricsRecalculation.Status.FAILED) & Q(completed_at__isnull=False))
    )


def get_latest_recalculation(experiment: Experiment) -> ExperimentMetricsRecalculation | None:
    with team_scope(experiment.team_id, canonical=True):
        return terminal_recalculations(experiment).order_by("-created_at").first()


def get_recalculation_by_id(experiment: Experiment, recalculation_id: str) -> ExperimentMetricsRecalculation | None:
    """Return the recalculation row for ``recalculation_id`` if it belongs to ``experiment``, else None.

    Enforces experiment scoping so the id-based GET cannot leak rows from a different experiment in the same team.
    Returns None for a malformed UUID rather than raising, so the calling view can answer with a clean 404.
    """
    try:
        uuid_value = UUID(recalculation_id)
    except (ValueError, TypeError):
        return None
    with team_scope(experiment.team_id, canonical=True):
        return ExperimentMetricsRecalculation.objects.filter(
            team=experiment.team, experiment=experiment, id=uuid_value
        ).first()
