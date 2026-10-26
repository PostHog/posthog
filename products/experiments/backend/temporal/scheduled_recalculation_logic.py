"""Selection rules for the scheduled experiment recalculation workflow.

Pure synchronous functions, no Temporal imports, so every rule is testable on its own. The
workflow's activities in `scheduled_recalculation_activities` are thin wrappers over these.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from django.db.models import Max, Prefetch, Q, QuerySet
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.ph_client import feature_enabled_or_false
from posthog.redis import get_client

from products.experiments.backend.hogql_queries import MULTIPLE_VARIANT_KEY
from products.experiments.backend.metric_resolution import get_metrics_for_calculation
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricsRecalculation,
    ExperimentToSavedMetric,
)
from products.feature_flags.backend.facade.config import ConfigFormatError
from products.feature_flags.backend.facade.filters import condition_rollout_percentage

if TYPE_CHECKING:
    from products.feature_flags.backend.models.feature_flag import FeatureFlag

logger = structlog.get_logger(__name__)

SCHEDULED_RECALCULATION_FEATURE_FLAG = "experiments-scheduled-recalculation"

# Matches the daily timeseries discovery in posthog/temporal/experiments/activities.py, so both
# systems agree on which experiments are worth computing.
EXPERIMENT_RECALCULATION_MAX_AGE_DAYS = 60

# An experiment younger than this has too little data for the queries to be worth their cost.
MIN_EXPERIMENT_AGE = timedelta(hours=12)

MIN_TOTAL_EXPOSURES = 50

# After this many consecutive checks below MIN_TOTAL_EXPOSURES, the exposure query runs only once
# per EXPOSURE_BACKOFF_INTERVAL. Without it, an experiment that stays below the floor costs one
# ClickHouse query at every scheduled hour of its team.
EXPOSURE_BACKOFF_MIN_CONSECUTIVE_CHECKS = 3
EXPOSURE_BACKOFF_INTERVAL = timedelta(days=7)
# Longer than the interval, so the count survives until the next check renews it.
EXPOSURE_BACKOFF_TTL = timedelta(days=14)
EXPOSURE_BACKOFF_KEY_PREFIX = "experiments:exposure_backoff:v1"

# A run finished inside this window already left fresh enough data on the page.
MIN_TIME_SINCE_LAST_RECALCULATION = timedelta(hours=1)

SKIP_INSUFFICIENT_EXPOSURES: Final = "insufficient_exposures"
SKIP_EXPOSURE_QUERY_FAILED: Final = "exposure_query_failed"
SKIP_ACTIVE_RUN: Final = "active_run_exists"
SKIP_RECENT_RUN: Final = "recent_run_exists"
SKIP_ZERO_ROLLOUT: Final = "zero_rollout"
SKIP_NO_METRICS: Final = "no_metrics"
SKIP_EXPOSURE_BACKOFF: Final = "exposure_backoff"
SKIP_DISPATCH_UNCERTAIN: Final = "dispatch_uncertain"
SKIP_START_WINDOW_ELAPSED: Final = "start_window_elapsed"

NEVER_SCHEDULED = datetime.min.replace(tzinfo=UTC)


@frozen
class ScheduledRecalculationCandidate:
    experiment_id: int
    team_id: int
    organization_id: str


@frozen
class ScheduledRecalculationDiscovery:
    """One hour's candidates, with the hour the run resolved, so callers report what it selected for."""

    hour: int
    candidates: list[ScheduledRecalculationCandidate]


@frozen
class SkipDecision:
    reason: str
    detail: dict[str, str | int | float | None]


@frozen
class ExposureBackoffState:
    consecutive_insufficient_checks: int
    checked_at: datetime


@frozen
class DiscoverySkip:
    experiment: Experiment
    decision: SkipDecision


@frozen
class ScheduledRecalculationSelection:
    """The discovery result, plus the experiments that discovery skipped.

    Only `discovery` leaves the activity. The skips hold model instances, so the activity reports
    them itself and never returns them to the workflow.
    """

    discovery: ScheduledRecalculationDiscovery
    skips: list[DiscoverySkip]


def team_has_scheduled_recalculation_enabled(team_id: int, organization_id: str) -> bool:
    return feature_enabled_or_false(
        SCHEDULED_RECALCULATION_FEATURE_FLAG,
        str(team_id),
        groups={"organization": organization_id, "project": str(team_id)},
        group_properties={"organization": {"id": organization_id}, "project": {"id": str(team_id)}},
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )


def find_scheduled_recalculation_candidates() -> ScheduledRecalculationSelection:
    """Experiments eligible for a scheduled recalculation right now, before the exposure gate.

    Reads the hour itself rather than taking it as a parameter, so one hourly schedule serves
    every team. An activity may read a clock; a workflow body may not.

    Skips, before any exposure query, every experiment that `_discovery_skip` rejects: a flag that
    can serve nobody, no metric that the recalculation would compute, an active run, a recent run,
    or an exposure back-off. The query count does not grow with the number of candidates.

    An exposure-frozen experiment stays eligible, because its metric events keep arriving.

    Candidates come oldest scheduled run first, so an experiment that the workflow deferred
    yesterday starts before the ones that ran.
    """
    # Deferred: importing this module runs posthog/temporal/experiments/__init__.py, which pulls
    # activities.py, which imports back into products.experiments.backend.facade.timeseries.
    from posthog.temporal.experiments.utils import recalculation_hour_filter  # noqa: PLC0415 — breaks that cycle

    now = timezone.now()
    hour = now.hour

    time_filter = recalculation_hour_filter(hour)

    rows = (
        Experiment.objects.filter(
            time_filter,
            deleted=False,
            status=Experiment.Status.RUNNING,
            # A paused experiment keeps status RUNNING and only deactivates its flag, so the stored
            # status alone would select one that collects no new data.
            feature_flag__active=True,
            start_date__gte=now - timedelta(days=EXPERIMENT_RECALCULATION_MAX_AGE_DAYS),
            start_date__lte=now - MIN_EXPERIMENT_AGE,
        )
        .values_list("id", "team_id", "team__organization_id")
        .order_by("id")
    )

    # Cache per team: the flag is evaluated locally, but a team with many experiments would
    # otherwise repeat the same lookup once per row.
    enabled_teams: dict[int, bool] = {}
    enabled_ids: list[int] = []
    for experiment_id, team_id, organization_id in rows:
        if team_id not in enabled_teams:
            enabled_teams[team_id] = team_has_scheduled_recalculation_enabled(team_id, str(organization_id))
        if enabled_teams[team_id]:
            enabled_ids.append(experiment_id)

    # Loaded only for enabled teams, so the metric definitions of every other team stay unread.
    experiments = list(
        Experiment.objects.filter(id__in=enabled_ids)
        .select_related("feature_flag", "team__organization", "created_by")
        .prefetch_related(
            Prefetch(
                "experimenttosavedmetric_set",
                queryset=ExperimentToSavedMetric.objects.select_related("saved_metric"),
            )
        )
        .order_by("id")
    )
    active_runs = _active_run_skips(enabled_ids)
    recent_runs = _recent_run_skips(enabled_ids)
    exposure_backoffs = _exposure_backoff_skips(enabled_ids)

    candidates: list[ScheduledRecalculationCandidate] = []
    skips: list[DiscoverySkip] = []
    for experiment in experiments:
        try:
            decision = _discovery_skip(
                experiment, active_runs=active_runs, recent_runs=recent_runs, exposure_backoffs=exposure_backoffs
            )
        except Exception:
            # One malformed flag or metric must not stop discovery for every team in this hour. The
            # experiment stays a candidate, and the exposure gate decides.
            logger.warning("scheduled_recalculation_skip_check_failed", experiment_id=experiment.id, exc_info=True)
            decision = None
        if decision is not None:
            skips.append(DiscoverySkip(experiment=experiment, decision=decision))
            continue
        candidates.append(
            ScheduledRecalculationCandidate(
                experiment_id=experiment.id,
                team_id=experiment.team_id,
                organization_id=str(experiment.team.organization_id),
            )
        )

    last_scheduled_runs = _last_scheduled_runs([c.experiment_id for c in candidates])
    candidates.sort(key=lambda c: (last_scheduled_runs.get(c.experiment_id, NEVER_SCHEDULED), c.experiment_id))

    logger.info("scheduled_recalculation_candidates", hour=hour, count=len(candidates), skipped=len(skips))
    return ScheduledRecalculationSelection(
        discovery=ScheduledRecalculationDiscovery(hour=hour, candidates=candidates), skips=skips
    )


def _discovery_skip(
    experiment: Experiment,
    *,
    active_runs: dict[int, SkipDecision],
    recent_runs: dict[int, SkipDecision],
    exposure_backoffs: dict[int, SkipDecision],
) -> SkipDecision | None:
    if not _flag_can_serve_anyone(experiment.feature_flag):
        return SkipDecision(reason=SKIP_ZERO_ROLLOUT, detail={})
    # The same rule the recalculation discovery applies, so a run started here never completes empty.
    if not get_metrics_for_calculation(experiment):
        return SkipDecision(reason=SKIP_NO_METRICS, detail={})
    return active_runs.get(experiment.id) or recent_runs.get(experiment.id) or exposure_backoffs.get(experiment.id)


def _flag_can_serve_anyone(flag: "FeatureFlag") -> bool:
    """Whether a release condition has a rollout above 0%. A flag without one never exposes a user.

    A flag in a config format other than version 1 stays eligible, and the exposure gate decides.
    """
    try:
        conditions = flag.conditions
    except ConfigFormatError:
        return True
    return any(condition_rollout_percentage(condition) > 0 for condition in conditions)


def _active_run_skip(recalculation_id: str) -> SkipDecision:
    return SkipDecision(reason=SKIP_ACTIVE_RUN, detail={"existing_recalculation_id": recalculation_id})


def _recent_run_skip(recalculation_id: str, completed_at: datetime) -> SkipDecision:
    minutes = int((timezone.now() - completed_at).total_seconds() // 60)
    return SkipDecision(
        reason=SKIP_RECENT_RUN,
        detail={"latest_recalculation_id": recalculation_id, "minutes_since_completion": minutes},
    )


def _recent_recalculations(
    queryset: QuerySet[ExperimentMetricsRecalculation],
) -> QuerySet[ExperimentMetricsRecalculation]:
    """Runs that finished inside the freshness window on a window of data that is itself recent.

    `timeseries_sync` rows never count toward freshness: they carry a timeseries run's window, not a
    full recalculation, and counting one would skip the experiment that needs the real run.
    """
    freshness_cutoff = timezone.now() - MIN_TIME_SINCE_LAST_RECALCULATION
    return (
        queryset.filter(completed_at__isnull=False, completed_at__gte=freshness_cutoff)
        # A reused window makes a run recent without making its data recent: `_resolve_query_to`
        # keeps the previous `query_to` for metric_config_change, manual_retry and heal_latest_run,
        # and the page heals itself on load, so this is a routine shape rather than a rare one. A
        # null `query_to` still counts, because such a run resolved no window to judge.
        .filter(Q(query_to__isnull=True) | Q(query_to__gte=freshness_cutoff))
        .exclude(trigger=ExperimentMetricsRecalculation.Trigger.TIMESERIES_SYNC)
    )


def _active_run_skips(experiment_ids: list[int]) -> dict[int, SkipDecision]:
    """The newest active run of each experiment, in one query across teams."""
    # Deferred: recalculation.py imports temporal.recalculation_logic at module level, so a
    # module-level import here closes a cycle back into a partially initialized module.
    from products.experiments.backend.recalculation import active_recalculation_filter  # noqa: PLC0415

    rows = (
        # Unscoped because the experiments belong to many teams. The filter on the discovered ids
        # keeps the read to those experiments' rows.
        ExperimentMetricsRecalculation.objects.unscoped()
        .filter(experiment_id__in=experiment_ids)
        .filter(active_recalculation_filter())
        .order_by("experiment_id", "-created_at")
        .values_list("experiment_id", "id")
    )
    skips: dict[int, SkipDecision] = {}
    for experiment_id, recalculation_id in rows:
        skips.setdefault(experiment_id, _active_run_skip(str(recalculation_id)))
    return skips


def _recent_run_skips(experiment_ids: list[int]) -> dict[int, SkipDecision]:
    """The latest recent run of each experiment, in one query across teams."""
    rows = (
        _recent_recalculations(
            ExperimentMetricsRecalculation.objects.unscoped().filter(experiment_id__in=experiment_ids)
        )
        .order_by("experiment_id", "-completed_at")
        .values_list("experiment_id", "id", "completed_at")
    )
    skips: dict[int, SkipDecision] = {}
    for experiment_id, recalculation_id, completed_at in rows:
        if completed_at is not None:
            skips.setdefault(experiment_id, _recent_run_skip(str(recalculation_id), completed_at))
    return skips


def _last_scheduled_runs(experiment_ids: list[int]) -> dict[int, datetime]:
    """When each experiment last got a scheduled run, in one query across teams."""
    rows = (
        ExperimentMetricsRecalculation.objects.unscoped()
        .filter(experiment_id__in=experiment_ids, trigger=ExperimentMetricsRecalculation.Trigger.SCHEDULED)
        .values("experiment_id")
        .annotate(last_created_at=Max("created_at"))
        .values_list("experiment_id", "last_created_at")
    )
    return dict(rows)


def _exposure_backoff_key(experiment_id: int) -> str:
    return f"{EXPOSURE_BACKOFF_KEY_PREFIX}:{experiment_id}"


def _parse_exposure_backoff_state(raw: bytes | str | None) -> ExposureBackoffState | None:
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        return ExposureBackoffState(
            consecutive_insufficient_checks=int(data["count"]),
            checked_at=datetime.fromtimestamp(float(data["checked_at"]), tz=UTC),
        )
    # OverflowError and OSError come from a timestamp outside the range that datetime accepts.
    except (ValueError, TypeError, KeyError, OverflowError, OSError):
        return None


def _exposure_backoff_skips(experiment_ids: list[int]) -> dict[int, SkipDecision]:
    """The experiments in an exposure back-off, read in one MGET across teams.

    Fails open: a Redis error or an unreadable value leaves the experiment a candidate, so the
    exposure gate decides as it would without the back-off.
    """
    if not experiment_ids:
        return {}
    try:
        values = get_client().mget([_exposure_backoff_key(experiment_id) for experiment_id in experiment_ids])
    except Exception:
        logger.warning("scheduled_recalculation_exposure_backoff_read_failed", exc_info=True)
        return {}

    now = timezone.now()
    skips: dict[int, SkipDecision] = {}
    for experiment_id, raw in zip(experiment_ids, values, strict=True):
        state = _parse_exposure_backoff_state(raw)
        if state is None or state.consecutive_insufficient_checks < EXPOSURE_BACKOFF_MIN_CONSECUTIVE_CHECKS:
            continue
        since_last_check = now - state.checked_at
        if since_last_check >= EXPOSURE_BACKOFF_INTERVAL:
            continue
        skips[experiment_id] = SkipDecision(
            reason=SKIP_EXPOSURE_BACKOFF,
            detail={
                "consecutive_insufficient_checks": state.consecutive_insufficient_checks,
                "days_since_last_check": round(since_last_check / timedelta(days=1), 1),
            },
        )
    return skips


def record_exposure_check(experiment_id: int, total_exposures: int) -> None:
    """Count one more consecutive check below MIN_TOTAL_EXPOSURES, or clear the count at or above it.

    Every write renews the TTL. A Redis error only logs: losing a count costs at most a few extra
    exposure queries, while a raised error would skip the experiment.
    """
    key = _exposure_backoff_key(experiment_id)
    try:
        client = get_client()
        if total_exposures >= MIN_TOTAL_EXPOSURES:
            client.delete(key)
            return
        previous = _parse_exposure_backoff_state(client.get(key))
        count = (previous.consecutive_insufficient_checks if previous else 0) + 1
        value = json.dumps({"count": count, "checked_at": timezone.now().timestamp()})
        client.set(key, value, ex=EXPOSURE_BACKOFF_TTL)
    except Exception:
        logger.warning(
            "scheduled_recalculation_exposure_backoff_write_failed", experiment_id=experiment_id, exc_info=True
        )


def recent_recalculation_skip(experiment: Experiment, team_id: int) -> SkipDecision | None:
    """Skip when a run is already active, or when one finished inside the freshness window on a
    window of data that is itself recent (`_recent_recalculations`).

    Discovery applies the same rules to the whole batch. This check catches a run that started
    between discovery and the start of this experiment.

    Scopes explicitly with `for_team`: the model is fail-closed and an activity carries no request
    context, so an unscoped read would raise `TeamScopeError`.

    `get_active_recalculation` owns the definition of "active", staleness bound included: nothing
    reaps an abandoned row in the background, so an unbounded check would lock the experiment out
    of every later scheduled run.
    """
    # Deferred: recalculation.py imports temporal.recalculation_logic at module level, so a
    # module-level import here closes a cycle back into a partially initialized module.
    from products.experiments.backend.recalculation import get_active_recalculation  # noqa: PLC0415 — breaks that cycle

    scoped = ExperimentMetricsRecalculation.objects.for_team(team_id)

    active = get_active_recalculation(experiment)
    if active is not None:
        return _active_run_skip(str(active.id))

    latest = _recent_recalculations(scoped.filter(experiment=experiment)).order_by("-completed_at").first()
    if latest is not None and latest.completed_at is not None:
        return _recent_run_skip(str(latest.id), latest.completed_at)

    return None


def count_total_exposures(experiment: Experiment) -> int:
    """Total exposed entities across variants, over the experiment's own window.

    The `$multiple` bucket holds entities that saw more than one variant, so it is not a
    variant's audience and does not count toward the threshold.
    """
    from posthog.clickhouse.query_tagging import Product, tags_context
    from posthog.hogql_queries.query_runner import ExecutionMode

    from products.experiments.backend.hogql_queries.experiment_exposures_query_runner import (
        ExperimentExposuresQueryRunner,
        build_experiment_exposure_query,
    )

    query = build_experiment_exposure_query(experiment)
    with tags_context(
        product=Product.EXPERIMENTS, team_id=experiment.team_id, org_id=str(experiment.team.organization_id)
    ):
        runner = ExperimentExposuresQueryRunner(query=query, team=experiment.team, error_event_context=None)
        response = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)

    total_exposures = getattr(response, "total_exposures", None) or {}
    return sum(value for key, value in total_exposures.items() if key != MULTIPLE_VARIANT_KEY)
