"""``request_recalculation`` — idempotent create: returns the active run if one exists, else creates a pending job."""

from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

import posthoganalytics
from prometheus_client import Counter
from rest_framework.exceptions import Throttled, ValidationError

from posthog.event_usage import groups
from posthog.exceptions_capture import capture_exception
from posthog.models.scoping import team_scope
from posthog.models.user import User

from products.experiments.backend.hogql_queries.base_query_utils import experiment_window_end
from products.experiments.backend.metric_resolution import get_metrics_for_calculation
from products.experiments.backend.models.experiment import Experiment, ExperimentMetricsRecalculation
from products.experiments.backend.organization_flags import organization_flag_enabled
from products.experiments.backend.temporal.models import RECALCULATION_WINDOW_TOO_LONG_ERROR_TYPE
from products.experiments.backend.temporal.recalculation.dispatch import cancel_superseded_workflows

from . import payloads, runs

# rate limiting manual reloads (including agents).
MIN_USER_RECALCULATION_INTERVAL = timedelta(minutes=5)

RECALCULATION_RATE_LIMIT_FEATURE_FLAG = "experiment-metric-recalculation-rate-limit"

_RATE_LIMITED_TRIGGERS = frozenset(
    {
        ExperimentMetricsRecalculation.Trigger.MANUAL,
        ExperimentMetricsRecalculation.Trigger.AGENT_MCP,
    }
)

# A run scans every event from the start date to now, so the oldest experiments make the most expensive
# ClickHouse queries. request_recalculation records them as rejected runs and starts no workflow.
RECALCULATION_MAX_EXPERIMENT_AGE = timedelta(days=180)

RECALCULATION_AGE_LIMIT_FEATURE_FLAG = "experiment-recalculation-age-limit"

RECALCULATION_REJECTED_EVENT = "experiment recalculation rejected"

RECALCULATION_WINDOW_TOO_LONG_MESSAGE = (
    "This experiment started too long ago for its metrics to be recalculated. "
    "To measure new data, start a new experiment or move the start date closer to today."
)


class RecalculationRateLimited(Throttled):
    """A user-driven trigger landed inside MIN_USER_RECALCULATION_INTERVAL. The API layer renders it as a 429
    with a Retry-After header, so a client or an agent knows when the next run is allowed."""

    # DRF sets this in Throttled.__init__ and its handler turns it into Retry-After; the stubs omit it.
    wait: float | None

    default_code = "recalculation_rate_limited"
    # DRF appends "Expected available in N seconds." to this, so the wait is not repeated here.
    default_detail = "Metrics were recalculated less than 5 minutes ago."


# Mirrors STALE_RESULTS_THRESHOLD_HOURS in experimentMetricsLogic.ts. The frontend judges staleness with the
# browser clock, so this server-side check stops a client clock that runs ahead from recalculating on every visit.
STALE_REFRESH_MIN_RESULT_AGE = timedelta(hours=12)

# `is_existing=True` reuse path — counts how often the idempotency guard saves us a workflow start.
# A sustained climb here without a matching climb in requests is the signal the frontend is double-posting.
_recalculation_reuse_counter = Counter(
    "experiment_metrics_recalculation_existing_run_reused",
    "POST requests that returned an existing active run instead of creating a new one (idempotent reuse).",
)

# Counts user-driven POSTs that landed inside MIN_USER_RECALCULATION_INTERVAL and got the latest run back.
_recalculation_rate_limited_counter = Counter(
    "experiment_metrics_recalculation_rate_limited",
    "POST requests answered with 429 because a user-driven run was requested inside the refresh window.",
)

# Fires whenever the 30-min staleness threshold marks a PENDING/IN_PROGRESS row FAILED so the experiment
# can recalculate again. A sustained climb is a leading indicator of Temporal connect failures or the
# rollback in start_metrics_recalculation_workflow itself failing.
_recalculation_stale_cleanup_counter = Counter(
    "experiment_metrics_recalculation_stale_rows_cleaned",
    "Stale recalc rows force-failed to release the per-experiment uniqueness constraint.",
)


def _refresh_window_enforced(experiment: Experiment) -> bool:
    # Local development skips the window so a developer can reload at will. Tests keep it, because they assert it.
    if settings.DEBUG and not settings.TEST:
        return False
    return organization_flag_enabled(RECALCULATION_RATE_LIMIT_FEATURE_FLAG, str(experiment.team.organization_id))


def _recalculation_max_age(experiment: Experiment) -> timedelta | None:
    # A flag error turns the limit off, so a flag outage never rejects a recalculation.
    try:
        enabled = organization_flag_enabled(RECALCULATION_AGE_LIMIT_FEATURE_FLAG, str(experiment.team.organization_id))
    except Exception as e:
        capture_exception(e)
        return None
    return RECALCULATION_MAX_EXPERIMENT_AGE if enabled else None


def _age_over_limit(experiment: Experiment, max_age: timedelta | None) -> timedelta | None:
    """The age of the experiment when it is older than `max_age`, otherwise None."""
    if max_age is None or experiment.start_date is None:
        return None
    age = timezone.now() - experiment.start_date
    return age if age > max_age else None


def exceeds_recalculation_age_limit(experiment: Experiment) -> bool:
    """Whether `request_recalculation` rejects this experiment because it started too long ago. Saved results stay
    readable either way."""
    return _age_over_limit(experiment, _recalculation_max_age(experiment)) is not None


def _capture_recalculation_rejected(
    recalc: ExperimentMetricsRecalculation, user: User | None, experiment_age: timedelta, max_age: timedelta
) -> None:
    # Telemetry must never fail the request, so every error is swallowed.
    try:
        team = recalc.experiment.team
        posthoganalytics.capture(
            distinct_id=user.distinct_id if user and user.distinct_id else f"team_{team.id}",
            event=RECALCULATION_REJECTED_EVENT,
            properties={
                "experiment_id": recalc.experiment_id,
                "team_id": team.id,
                "organization_id": str(team.organization_id),
                "trigger": recalc.trigger,
                "recalculation_id": str(recalc.id),
                "experiment_age_days": experiment_age.days,
                "max_age_days": max_age.days,
            },
            groups=groups(organization=team.organization, team=team),
        )
    except Exception as e:
        capture_exception(e)


def _create_rejected_recalculation(
    experiment: Experiment, user: User | None, trigger: str, experiment_age: timedelta, max_age: timedelta
) -> ExperimentMetricsRecalculation:
    """A terminal FAILED run with the window error on every metric. Callers hold the team scope and the lock.

    completed_at makes the run the latest one, so a reload shows the error and no page-load heal runs again.
    The run takes query_to from the latest terminal run, so the results lookup of this run returns the rows
    of that run and the earlier results stay readable.
    """
    now = timezone.now()
    previous = runs.terminal_recalculations(experiment).order_by("-created_at").first()
    metrics = get_metrics_for_calculation(experiment)
    error = {
        "step": "request",
        "message": RECALCULATION_WINDOW_TOO_LONG_MESSAGE,
        "error_type": RECALCULATION_WINDOW_TOO_LONG_ERROR_TYPE,
        "retriable": False,
        "timestamp": now.isoformat(),
    }
    recalc = ExperimentMetricsRecalculation.objects.create(
        team=experiment.team,
        experiment=experiment,
        trigger=trigger,
        status=ExperimentMetricsRecalculation.Status.FAILED,
        created_by=user,
        total_metrics=len(metrics),
        metric_uuids=[m.uuid for m in metrics],
        metric_errors={m.uuid: dict(error) for m in metrics},
        query_to=previous.query_to if previous is not None else None,
        completed_at=now,
    )
    transaction.on_commit(lambda: _capture_recalculation_rejected(recalc, user, experiment_age, max_age))
    return recalc


def request_recalculation(experiment: Experiment, user: User | None, trigger: str = "manual") -> dict:
    """Create an idempotent batch recalculation request for all experiment metrics.

    If an active (pending or in_progress) run already exists for this experiment, returns the existing run's
    serialized payload with ``is_existing=True`` — the caller should NOT start a new workflow in that case.
    When the organization has the age-limit flag on, an experiment that started more than
    ``RECALCULATION_MAX_EXPERIMENT_AGE`` ago gets a rejected run: status FAILED, ``is_existing=False``, and the
    caller must not start a workflow for it either. A user-driven trigger inside
    ``MIN_USER_RECALCULATION_INTERVAL`` after the latest completed run finished raises
    ``RecalculationRateLimited`` when the organization has the rate-limit flag on. A ``stale_refresh`` whose
    latest terminal run is not stale (``_results_are_stale``) returns that run with ``is_existing=True``, and the
    caller must not start a workflow. Otherwise creates a fresh pending row.
    """
    return _request_recalculation(experiment, user, trigger, max_age=_recalculation_max_age(experiment))


def request_recalculation_without_age_limit(experiment: Experiment, user: User | None, trigger: str) -> dict:
    """``request_recalculation`` without the experiment age limit, so staff can still recalculate an old
    experiment from the admin panel."""
    return _request_recalculation(experiment, user, trigger, max_age=None)


def _request_recalculation(
    experiment: Experiment, user: User | None, trigger: str, *, max_age: timedelta | None
) -> dict:
    if not experiment.is_launched:
        raise ValidationError("Cannot recalculate metrics for experiment that hasn't started")

    with team_scope(experiment.team_id, canonical=True), transaction.atomic():
        # Serialize concurrent POSTs for this experiment by locking the Experiment row up front. Without this,
        # two simultaneous POSTs (double-click, retry storm, two tabs) both see no active recalc row and both
        # reach .create(); the second hits the unique_active_metrics_recalculation_per_experiment constraint
        # and returns HTTP 500. Locking the Experiment row queues the second POST behind the first, which
        # then sees the freshly-created row in its lookup and returns is_existing=True cleanly.
        Experiment.objects.select_for_update().filter(id=experiment.id).first()

        # Activity-aware staleness: PENDING rows anchor on created_at (workflow never reached its start
        # activity); IN_PROGRESS rows anchor on started_at (workflow began executing then stalled). A row past
        # the threshold is skipped here, and queued_recalculation below decides whether it is still alive.
        # Without this, a PENDING row left orphaned by a Temporal-connect failure that also lost its rollback
        # UPDATE would permanently lock the experiment out of recalculations.
        threshold = timezone.now() - runs.STALE_RECALC_THRESHOLD
        existing = (
            ExperimentMetricsRecalculation.objects.filter(experiment=experiment)
            .filter(
                Q(status=ExperimentMetricsRecalculation.Status.PENDING, created_at__gte=threshold)
                | Q(status=ExperimentMetricsRecalculation.Status.IN_PROGRESS, started_at__gte=threshold)
            )
            .first()
        )
        if existing:
            _recalculation_reuse_counter.inc()
            return payloads.build_job_payload(existing, is_existing=True)

        queued = runs.queued_recalculation(experiment)
        if queued is not None:
            _recalculation_reuse_counter.inc()
            return payloads.build_job_payload(queued, is_existing=True)

        if trigger in _RATE_LIMITED_TRIGGERS and _refresh_window_enforced(experiment):
            # get the latest terminal run and check against the rate limiting rules
            # if matched, increment counter and raise so the API answers 429 with Retry-After
            latest = runs.terminal_recalculations(experiment).order_by("-created_at").first()
            if (
                latest is not None
                and latest.status == ExperimentMetricsRecalculation.Status.COMPLETED
                and latest.trigger != ExperimentMetricsRecalculation.Trigger.TIMESERIES_SYNC
                and latest.completed_at is not None
                and latest.completed_at >= timezone.now() - MIN_USER_RECALCULATION_INTERVAL
            ):
                _recalculation_rate_limited_counter.inc()
                next_allowed_at = latest.completed_at + MIN_USER_RECALCULATION_INTERVAL
                raise RecalculationRateLimited(wait=(next_allowed_at - timezone.now()).total_seconds())

        if trigger == ExperimentMetricsRecalculation.Trigger.STALE_REFRESH:
            latest = runs.terminal_recalculations(experiment).order_by("-created_at").first()
            if (
                latest is not None
                and latest.query_to is not None
                and not _results_are_stale(experiment, latest.query_to)
            ):
                return payloads.build_job_payload(latest, is_existing=True)

        # No fresh active row, but stale tombstones might still hold the per-experiment uniqueness constraint
        # (unique_active_metrics_recalculation_per_experiment). Mark them FAILED so the constraint releases
        # and the new row can land, and cancel their workflows after commit — a superseded run that is still
        # executing would otherwise keep burning worker slots and ClickHouse quota alongside its replacement.
        stale_ids = list(
            ExperimentMetricsRecalculation.objects.filter(
                experiment=experiment,
                status__in=[
                    ExperimentMetricsRecalculation.Status.PENDING,
                    ExperimentMetricsRecalculation.Status.IN_PROGRESS,
                ],
            ).values_list("id", flat=True)
        )
        if stale_ids:
            # No completed_at: that stamp is reserved for the workflow finalize step, and its absence is
            # what keeps superseded/tombstone rows out of get_latest_recalculation.
            ExperimentMetricsRecalculation.objects.filter(
                team=experiment.team, experiment=experiment, id__in=stale_ids
            ).update(status=ExperimentMetricsRecalculation.Status.FAILED)
            _recalculation_stale_cleanup_counter.inc(len(stale_ids))
            transaction.on_commit(lambda: cancel_superseded_workflows([str(stale_id) for stale_id in stale_ids]))

        # After the stale cleanup, so a stale run of an old experiment is failed and its workflow cancelled too.
        if max_age is not None and (experiment_age := _age_over_limit(experiment, max_age)) is not None:
            rejected = _create_rejected_recalculation(experiment, user, trigger, experiment_age, max_age)
            return payloads.build_job_payload(rejected, is_existing=False)

        # Set total_metrics up front from the experiment definition so the client can show progress
        # ("N of M") immediately, before the workflow's discovery activity confirms the same count.
        metrics = get_metrics_for_calculation(experiment)
        recalc = ExperimentMetricsRecalculation.objects.create(
            team=experiment.team,
            experiment=experiment,
            trigger=trigger,
            status=ExperimentMetricsRecalculation.Status.PENDING,
            created_by=user,
            total_metrics=len(metrics),
            metric_uuids=[m.uuid for m in metrics],
        )
        return payloads.build_job_payload(recalc, is_existing=False)


def _results_are_stale(experiment: Experiment, query_to: datetime) -> bool:
    """Whether results stop at least STALE_REFRESH_MIN_RESULT_AGE before the window end, which is now for a running
    experiment and the end date for a stopped one. Mirrors resultsAreStale in experimentMetricsLogic.ts."""
    return experiment_window_end(experiment, timezone.now()) - query_to >= STALE_REFRESH_MIN_RESULT_AGE
