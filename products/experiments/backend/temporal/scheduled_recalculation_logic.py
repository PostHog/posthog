"""Selection rules for the scheduled experiment recalculation workflow.

Pure synchronous functions, no Temporal imports, so every rule is testable on its own. The
workflow's activities in `scheduled_recalculation_activities` are thin wrappers over these.
"""

from datetime import timedelta
from typing import Final

from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.ph_client import feature_enabled_or_false

from products.experiments.backend.hogql_queries import MULTIPLE_VARIANT_KEY
from products.experiments.backend.models.experiment import Experiment, ExperimentMetricsRecalculation

logger = structlog.get_logger(__name__)

SCHEDULED_RECALCULATION_FEATURE_FLAG = "experiments-scheduled-recalculation"

# Matches the daily timeseries discovery in posthog/temporal/experiments/activities.py, so both
# systems agree on which experiments are worth computing.
EXPERIMENT_RECALCULATION_MAX_AGE_DAYS = 60

# An experiment younger than this has too little data for the queries to be worth their cost.
MIN_EXPERIMENT_AGE = timedelta(hours=12)

MIN_TOTAL_EXPOSURES = 50

# A run finished inside this window already left fresh enough data on the page.
MIN_TIME_SINCE_LAST_RECALCULATION = timedelta(hours=1)

SKIP_INSUFFICIENT_EXPOSURES: Final = "insufficient_exposures"
SKIP_EXPOSURE_QUERY_FAILED: Final = "exposure_query_failed"
SKIP_ACTIVE_RUN: Final = "active_run_exists"
SKIP_RECENT_RUN: Final = "recent_run_exists"


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


def team_has_scheduled_recalculation_enabled(team_id: int, organization_id: str) -> bool:
    return feature_enabled_or_false(
        SCHEDULED_RECALCULATION_FEATURE_FLAG,
        str(team_id),
        groups={"organization": organization_id, "project": str(team_id)},
        group_properties={"organization": {"id": organization_id}, "project": {"id": str(team_id)}},
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )


def find_scheduled_recalculation_candidates() -> ScheduledRecalculationDiscovery:
    """Experiments eligible for a scheduled recalculation right now, before the exposure gate.

    Reads the hour itself rather than taking it as a parameter, so one hourly schedule serves
    every team. An activity may read a clock; a workflow body may not.

    Deliberately applies no metrics filter: an experiment with no metrics gets a run, and the
    recalculation workflow completes it immediately.

    An exposure-frozen experiment stays eligible, because its metric events keep arriving.
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
    candidates: list[ScheduledRecalculationCandidate] = []
    for experiment_id, team_id, organization_id in rows:
        if team_id not in enabled_teams:
            enabled_teams[team_id] = team_has_scheduled_recalculation_enabled(team_id, str(organization_id))
        if not enabled_teams[team_id]:
            continue
        candidates.append(
            ScheduledRecalculationCandidate(
                experiment_id=experiment_id, team_id=team_id, organization_id=str(organization_id)
            )
        )

    logger.info("scheduled_recalculation_candidates", hour=hour, count=len(candidates))
    return ScheduledRecalculationDiscovery(hour=hour, candidates=candidates)


def recent_recalculation_skip(experiment: Experiment, team_id: int) -> SkipDecision | None:
    """Skip when a run is already active, or when one finished inside the freshness window.

    `timeseries_sync` rows never count toward freshness. Nothing writes them any more, but rows
    from before the timeseries workflow stopped publishing are still on file.

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
        return SkipDecision(reason=SKIP_ACTIVE_RUN, detail={"existing_recalculation_id": str(active.id)})

    latest = (
        scoped.filter(
            experiment=experiment,
            completed_at__isnull=False,
            completed_at__gte=timezone.now() - MIN_TIME_SINCE_LAST_RECALCULATION,
        )
        .exclude(trigger=ExperimentMetricsRecalculation.Trigger.TIMESERIES_SYNC)
        .order_by("-completed_at")
        .first()
    )
    if latest is not None and latest.completed_at is not None:
        minutes = int((timezone.now() - latest.completed_at).total_seconds() // 60)
        return SkipDecision(
            reason=SKIP_RECENT_RUN,
            detail={"latest_recalculation_id": str(latest.id), "minutes_since_completion": minutes},
        )

    return None


def count_total_exposures(experiment: Experiment) -> int:
    """Total exposed entities across variants, over the experiment's own window.

    The `$multiple` bucket holds entities that saw more than one variant, so it is not a
    variant's audience and does not count toward the threshold.
    """
    from posthog.schema import ExperimentExposureQuery  # noqa: PLC0415 — keeps the schema import off the module path

    from posthog.clickhouse.query_tagging import Product, tags_context
    from posthog.hogql_queries.query_runner import ExecutionMode

    from products.experiments.backend.hogql_queries.experiment_exposures_query_runner import (
        ExperimentExposuresQueryRunner,
    )

    feature_flag = experiment.feature_flag
    # The FK gives a model instance, and the query field is a pydantic type with no
    # attribute-based validation, so it must be serialized first.
    experiment_holdout = experiment.holdout
    holdout = (
        {"id": experiment_holdout.id, "name": experiment_holdout.name, "filters": experiment_holdout.filters}
        if experiment_holdout is not None
        else None
    )
    query = ExperimentExposureQuery(
        experiment_id=experiment.id,
        experiment_name=experiment.name,
        feature_flag={"key": feature_flag.key, "filters": feature_flag.filters},
        start_date=experiment.start_date.isoformat() if experiment.start_date else None,
        end_date=experiment.end_date.isoformat() if experiment.end_date else None,
        exposure_criteria=experiment.exposure_criteria,
        holdout=holdout,
    )
    with tags_context(
        product=Product.EXPERIMENTS, team_id=experiment.team_id, org_id=str(experiment.team.organization_id)
    ):
        runner = ExperimentExposuresQueryRunner(query=query, team=experiment.team, error_event_context=None)
        response = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)

    total_exposures = getattr(response, "total_exposures", None) or {}
    return sum(value for key, value in total_exposures.items() if key != MULTIPLE_VARIANT_KEY)
