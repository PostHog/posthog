"""The scheduled anomaly scoring tick: a Temporal workflow that scores the due active insights.

The `anomaly-scoring` flag payload holds every lever, and a missing or malformed payload turns the
tick off. Each insight activity scores one insight and writes its new buckets as `$anomaly_score` events.
"""

import time
import asyncio
import datetime
import dataclasses
from collections import Counter

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

from posthog.hogql.errors import QueryError, TableAccessDeniedError

from posthog.dataclasses import frozen
from posthog.exceptions import (
    ClickHouseAtCapacity,
    ClickHouseClusterMemoryLimitExceeded,
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.models import Team
from posthog.ph_client import ph_background_capture
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.product_analytics.backend.facade.api import insights_including_soft_deleted_for_team
from products.signals.backend.anomaly_scores.artifacts import ArtifactUnavailableError, load_artifacts, write_artifacts
from products.signals.backend.anomaly_scores.config import (
    ANOMALY_SCORING_FLAG_DISTINCT_ID,
    DEFAULT_LIMITS,
    ScoringLimits,
    ScoringRun,
    read_config,
    read_payload,
    resolve_profile,
)
from products.signals.backend.anomaly_scores.emission import emit, score_events
from products.signals.backend.anomaly_scores.metrics import record_candidates, record_pick
from products.signals.backend.anomaly_scores.queue import (
    ATTEMPT_COOLDOWN,
    SKIP_COOLDOWN,
    InsightPick,
    TeamCensus,
    mark_attempted,
    select_insights,
)
from products.signals.backend.anomaly_scores.scoring import (
    SCORING_QUERY_BUDGET_SECONDS,
    SplitRun,
    UnsupportedInsightError,
    score_insight,
)
from products.signals.backend.anomaly_scores.selection import parse_selection_config
from products.signals.backend.anomaly_scores.state import invalidate_state, load_state, save_state

logger = structlog.get_logger(__name__)

TICK_WORKFLOW_NAME = "anomaly-scoring-tick"

STATUS_SCORED = "scored"
# Scored, with no completed bucket newer than the ones already written.
STATUS_UP_TO_DATE = "up_to_date"
STATUS_UNSUPPORTED = "unsupported"
STATUS_MISSING = "missing"
# The scoring query hit a ClickHouse time or memory limit. A retry in an hour hits it again.
STATUS_TOO_EXPENSIVE = "too_expensive"
# The insight's creator cannot read a table of the query.
STATUS_ACCESS_DENIED = "access_denied"
# The saved query is invalid, for example it reads a warehouse table that no longer exists.
STATUS_BROKEN_QUERY = "broken_query"
# ClickHouse rejected the query because it is full. The tick starts no more picks.
STATUS_AT_CAPACITY = "at_capacity"
# The stored artifact blob is missing or does not match its hash. The next visit trains.
STATUS_ARTIFACT_UNAVAILABLE = "artifact_unavailable"
# Any other failure. The activity raises it, and the workflow counts it as `errored`.
STATUS_ERRORED = "errored"

_PLAN_TIMEOUT = datetime.timedelta(minutes=2)
# No team starts to load after this time. The rest of the plan scales with the loaded teams, so it needs the other half.
# A timed-out attempt does not stop its thread, so a plan that ends in time also keeps its retry from overlapping it.
_PLAN_LOAD_BUDGET = _PLAN_TIMEOUT / 2
# All the scoring queries of one insight stop within their budget. The rest is detection, the capture request,
# and the failure classification. A query timeout must reach the classification, so that it gets the 1 day cooldown.
_INSIGHT_TIMEOUT = datetime.timedelta(seconds=SCORING_QUERY_BUDGET_SECONDS) + datetime.timedelta(seconds=90)
_INSIGHT_HEARTBEAT_TIMEOUT = datetime.timedelta(minutes=1)
_CAPTURE_TIMEOUT = datetime.timedelta(minutes=1)
# No batch of insights starts after this time. The picks that are left wait for a later tick.
TICK_BUDGET = datetime.timedelta(minutes=10)
# A census key lives past its UTC day, so a tick at the end of the day still reads it.
_CENSUS_TTL = datetime.timedelta(days=2)
# The last batch can start at the budget, and the summary capture runs after it.
TICK_TIMEOUT = _PLAN_TIMEOUT + TICK_BUDGET + _INSIGHT_TIMEOUT + _CAPTURE_TIMEOUT


@frozen
class AnomalyScoringTickInput:
    # A manual run can override the per-tick cap of the flag.
    limit: int | None = None


@frozen
class AnomalyScoringTickPlan:
    enabled: bool
    picks: list[InsightPick]
    candidates: int
    max_concurrency: int
    limits: ScoringLimits = DEFAULT_LIMITS
    skipped_for_budget: int = 0
    picked_score: int = 0
    picked_train: int = 0
    scored_stale_model: int = 0
    train_backlog_soft: int = 0
    train_backlog_hard: int = 0
    active: int = 0
    active_reasons: dict[str, int] | None = None
    enrolled_teams: int = 0
    enrolled_organizations: int = 0
    teams_planned: int = 0
    teams_skipped: int = 0


@frozen
class ScoreInsightInput:
    pick: InsightPick
    limits: ScoringLimits = DEFAULT_LIMITS


@frozen
class ScoreInsightResult:
    status: str
    events: int
    series: int = 0
    # What the visit ran. A score pick with no matching state trains. None when the split is off.
    run: ScoringRun | None = None
    # Series of a score step with no stored artifact, and stored series missing from its result.
    unmatched_series: int = 0
    missing_series: int = 0


@frozen
class AnomalyScoringTickResult:
    enabled: bool = False
    candidates: int = 0
    picked: int = 0
    statuses: dict[str, int] | None = None
    errored: int = 0
    events: int = 0
    duration_ms: int = 0
    # Picks left for a later tick because the tick budget ran out.
    deferred: int = 0
    # The query cost of the picks that started.
    queries: int = 0
    skipped_for_budget: int = 0
    stopped_at_capacity: bool = False
    # Started picks per kind of the train and score split.
    run_train: int = 0
    run_score: int = 0
    # Planned picks of the score pass and of the train pass, started or not.
    picked_score: int = 0
    picked_train: int = 0
    # Planned score pass picks with a model due for a soft retrain, and the due train candidates left unpicked.
    scored_stale_model: int = 0
    train_backlog_soft: int = 0
    train_backlog_hard: int = 0
    # Active insights of the eligible teams, and how many of them have each activity reason.
    active: int = 0
    active_reasons: dict[str, int] | None = None
    enrolled_teams: int = 0
    enrolled_organizations: int = 0
    # Time of the plan activity, its retry included. Compare it with the plan timeout.
    plan_ms: int = 0
    # Teams with active insights that the plan loaded, and the teams that wait for a later tick.
    teams_planned: int = 0
    teams_skipped: int = 0
    # The plan activity failed, and the tick scored nothing. `plan_error` is the error class.
    plan_failed: bool = False
    plan_error: str | None = None


def plan_tick(limit: int | None, now: datetime.datetime) -> AnomalyScoringTickPlan:
    # One read, so the scoring and selection levers come from the same payload.
    payload = read_payload()
    config = read_config(payload)
    if not config.enabled:
        return AnomalyScoringTickPlan(enabled=False, picks=[], candidates=0, max_concurrency=config.max_concurrency)
    deadline = time.monotonic() + _PLAN_LOAD_BUDGET.total_seconds()
    selection = select_insights(config, parse_selection_config(payload), now, limit, deadline=deadline)
    record_candidates(selection.candidates)
    capture_census(selection.census, now)
    return AnomalyScoringTickPlan(
        enabled=True,
        picks=selection.picks,
        candidates=selection.candidates,
        max_concurrency=config.max_concurrency,
        limits=config.limits,
        skipped_for_budget=selection.skipped_for_budget,
        picked_score=selection.picked_score,
        picked_train=selection.picked_train,
        scored_stale_model=selection.scored_stale_model,
        train_backlog_soft=selection.train_backlog_soft,
        train_backlog_hard=selection.train_backlog_hard,
        active=selection.active,
        active_reasons=selection.active_reasons,
        enrolled_teams=selection.enrolled_teams,
        enrolled_organizations=selection.enrolled_organizations,
        teams_planned=selection.teams_planned,
        teams_skipped=selection.teams_skipped,
    )


def plan_error_class(error: ActivityError) -> str:
    """The class of the error that failed the plan activity. An activity timeout is a Temporal `TimeoutError`."""
    cause = error.cause
    if isinstance(cause, ApplicationError) and cause.type:
        return cause.type
    return type(cause).__name__ if cause is not None else type(error).__name__


def failure_status(error: Exception) -> str | None:
    """The status of a known failure, or None for any other failure."""
    if isinstance(error, UnsupportedInsightError):
        return STATUS_UNSUPPORTED
    if isinstance(error, ClickHouseAtCapacity):
        return STATUS_AT_CAPACITY
    # The cluster limit is a subclass of the query limit, but it is load from other queries, so a later tick can pass.
    if isinstance(error, ClickHouseClusterMemoryLimitExceeded):
        return None
    if isinstance(
        error,
        ClickHouseQueryTimeOut | ClickHouseQueryMemoryLimitExceeded | ClickHouseEstimatedQueryExecutionTimeTooLong,
    ):
        return STATUS_TOO_EXPENSIVE
    # A subclass of QueryError, so check it first.
    if isinstance(error, TableAccessDeniedError):
        return STATUS_ACCESS_DENIED
    # Only the exposed invalid-query error, such as an unknown table. ResolutionError is internal to the engine.
    if isinstance(error, QueryError):
        return STATUS_BROKEN_QUERY
    return None


def run_insight(input: ScoreInsightInput, now: datetime.datetime) -> ScoreInsightResult:
    """Score one pick, and log and measure its outcome. A known failure returns its status, and any other one raises."""
    pick = input.pick
    interval = pick.interval.value if pick.interval else "unknown"
    started = time.monotonic()
    try:
        result = _score_pick(input, now)
    except Exception as error:
        status = failure_status(error)
        duration_ms = round((time.monotonic() - started) * 1000)
        log = logger.info if status else logger.exception
        log(
            "anomaly_scoring_insight_failed",
            team_id=pick.team_id,
            insight_id=pick.insight_id,
            interval=interval,
            status=status or STATUS_ERRORED,
            error_class=type(error).__name__,
            error=str(error)[:200],
            duration_ms=duration_ms,
        )
        record_pick(status=status or STATUS_ERRORED, interval=interval, duration_ms=duration_ms, events=0, run=pick.run)
        capture_pick(pick, status=status or STATUS_ERRORED, interval=interval, duration_ms=duration_ms, run=pick.run)
        if status is None:
            raise
        # A full cluster is not a fault of the insight, so it keeps the attempt cooldown.
        if status != STATUS_AT_CAPACITY:
            mark_attempted(pick.insight_id, SKIP_COOLDOWN)
        return ScoreInsightResult(status=status, events=0)
    duration_ms = round((time.monotonic() - started) * 1000)
    logger.info(
        "anomaly_scoring_insight_scored",
        team_id=pick.team_id,
        insight_id=pick.insight_id,
        interval=interval,
        status=result.status,
        series=result.series,
        events=result.events,
        duration_ms=duration_ms,
        run=result.run,
        unmatched_series=result.unmatched_series,
        missing_series=result.missing_series,
    )
    record_pick(status=result.status, interval=interval, duration_ms=duration_ms, events=result.events, run=result.run)
    capture_pick(
        pick,
        status=result.status,
        interval=interval,
        duration_ms=duration_ms,
        run=result.run,
        series=result.series,
        events=result.events,
    )
    return result


def capture_pick(
    pick: InsightPick,
    *,
    status: str,
    interval: str,
    duration_ms: int,
    run: ScoringRun | None,
    series: int = 0,
    events: int = 0,
) -> None:
    """One event per pick, with the ids that the SDK metrics leave out, so cost and outcome break down per project."""
    ph_background_capture()(
        distinct_id=ANOMALY_SCORING_FLAG_DISTINCT_ID,
        event="anomaly scoring pick",
        properties={
            "deployment": settings.CLOUD_DEPLOYMENT,
            "team_id": pick.team_id,
            "insight_id": pick.insight_id,
            "interval": interval,
            "run": run,
            "status": status,
            "duration_ms": duration_ms,
            "series": series,
            "events": events,
            "queries": pick.query_cost,
        },
    )


def _census_key(team_id: int, day: datetime.date) -> str:
    return f"signals:anomaly_scoring:census:{day.isoformat()}:{team_id}"


def capture_census(census: list[TeamCensus], now: datetime.datetime) -> None:
    """One event per eligible team per UTC day, from the first tick of the day that sees the team."""
    day = now.astimezone(datetime.UTC).date()
    sent = cache.get_many([_census_key(team.team_id, day) for team in census])
    capture = ph_background_capture()
    for team in census:
        key = _census_key(team.team_id, day)
        # `add` sets the key only when it is missing, so two ticks that overlap send one event.
        if key in sent or not cache.add(key, True, timeout=_CENSUS_TTL.total_seconds()):
            continue
        capture(
            distinct_id=ANOMALY_SCORING_FLAG_DISTINCT_ID,
            event="anomaly scoring team census",
            properties={
                "deployment": settings.CLOUD_DEPLOYMENT,
                "team_id": team.team_id,
                "day": day.isoformat(),
                "active_insights": team.active,
                **{f"active_{reason}": count for reason, count in team.active_reasons.items()},
                **{f"interval_{interval}": count for interval, count in team.active_intervals.items()},
            },
        )


def _score_pick(input: ScoreInsightInput, now: datetime.datetime) -> ScoreInsightResult:
    pick = input.pick
    insight = next(
        (
            insight
            for insight in insights_including_soft_deleted_for_team(team_id=pick.team_id, insight_ids=[pick.insight_id])
            if insight.saved and not insight.deleted
        ),
        None,
    )
    if insight is None:
        return ScoreInsightResult(status=STATUS_MISSING, events=0)
    team = Team.objects.get(id=pick.team_id)
    # Set before scoring, so a failure also waits for the cooldown instead of taking a slot on every tick.
    mark_attempted(pick.insight_id, ATTEMPT_COOLDOWN)
    profile = resolve_profile(team, insight).name
    split = None
    if pick.run is not None:
        split = SplitRun()
        state = load_state(team, insight) if pick.run == ScoringRun.SCORE else None
        if state is not None:
            try:
                split = SplitRun(state=state, artifacts=load_artifacts(state.artifact_key, state.artifact_sha256))
            except ArtifactUnavailableError as error:
                logger.warning(
                    "anomaly_scoring_artifact_unavailable",
                    team_id=team.id,
                    insight_id=insight.id,
                    error=str(error)[:200],
                )
                invalidate_state(team, insight.id, profile)
                return ScoreInsightResult(status=STATUS_ARTIFACT_UNAVAILABLE, events=0, run=ScoringRun.SCORE)
    scores = score_insight(
        insight,
        team,
        now=now,
        # Every series is filtered again on its own newest bucket below. A new series gets up to the backfill cap.
        after=min(pick.scored_through.values()) if pick.scored_through else None,
        limits=input.limits,
        split=split,
    )
    if scores.artifacts and scores.state is not None:
        # The blob goes first, so every event of this visit names a model that exists.
        stored = write_artifacts(team.id, insight.id, profile, scores.artifacts)
        scores = dataclasses.replace(
            scores,
            model_id=stored.model_id,
            state=dataclasses.replace(scores.state, artifact_key=stored.key, artifact_sha256=stored.sha256),
        )
    events = score_events(
        team_id=team.id, insight_id=insight.id, scores=scores, scored_through=pick.scored_through, scored_at=now
    )
    emit(team, events)
    # After the emit: a lost state write only scores buckets again, and their events collapse by uuid.
    # A state write before a failed emit would skip those buckets for good.
    if scores.state is not None:
        save_state(team, insight.id, profile, scores.state)
    return ScoreInsightResult(
        status=STATUS_SCORED if events else STATUS_UP_TO_DATE,
        events=len(events),
        series=len(scores.series),
        run=scores.run,
        unmatched_series=scores.unmatched_series,
        missing_series=scores.state.missing_series if scores.state else 0,
    )


def capture_tick(result: AnomalyScoringTickResult) -> None:
    logger.info(
        "anomaly_scoring_tick_finished",
        candidates=result.candidates,
        picked=result.picked,
        statuses=result.statuses,
        errored=result.errored,
        events=result.events,
        duration_ms=result.duration_ms,
        deferred=result.deferred,
        queries=result.queries,
        skipped_for_budget=result.skipped_for_budget,
        stopped_at_capacity=result.stopped_at_capacity,
        run_train=result.run_train,
        run_score=result.run_score,
        picked_score=result.picked_score,
        picked_train=result.picked_train,
        scored_stale_model=result.scored_stale_model,
        train_backlog_soft=result.train_backlog_soft,
        train_backlog_hard=result.train_backlog_hard,
        active=result.active,
        active_reasons=result.active_reasons,
        enrolled_teams=result.enrolled_teams,
        enrolled_organizations=result.enrolled_organizations,
        plan_ms=result.plan_ms,
        teams_planned=result.teams_planned,
        teams_skipped=result.teams_skipped,
        plan_failed=result.plan_failed,
        plan_error=result.plan_error,
    )
    ph_background_capture()(
        distinct_id=ANOMALY_SCORING_FLAG_DISTINCT_ID,
        event="anomaly scoring tick",
        properties={
            "deployment": settings.CLOUD_DEPLOYMENT,
            "candidates": result.candidates,
            "picked": result.picked,
            **{f"status_{status}": count for status, count in (result.statuses or {}).items()},
            "errored": result.errored,
            "events": result.events,
            "duration_ms": result.duration_ms,
            "deferred": result.deferred,
            "queries": result.queries,
            "skipped_for_budget": result.skipped_for_budget,
            "stopped_at_capacity": result.stopped_at_capacity,
            "run_train": result.run_train,
            "run_score": result.run_score,
            "picked_score": result.picked_score,
            "picked_train": result.picked_train,
            "scored_stale_model": result.scored_stale_model,
            "train_backlog_soft": result.train_backlog_soft,
            "train_backlog_hard": result.train_backlog_hard,
            "active_insights": result.active,
            **{f"active_{reason}": count for reason, count in (result.active_reasons or {}).items()},
            "enrolled_teams": result.enrolled_teams,
            "enrolled_organizations": result.enrolled_organizations,
            "plan_ms": result.plan_ms,
            "teams_planned": result.teams_planned,
            "teams_skipped": result.teams_skipped,
            "plan_failed": result.plan_failed,
            "plan_error": result.plan_error,
        },
    )


@activity.defn
@scoped_temporal()
@close_db_connections
async def plan_anomaly_scoring_tick_activity(input: AnomalyScoringTickInput) -> AnomalyScoringTickPlan:
    return await database_sync_to_async(plan_tick, thread_sensitive=False)(input.limit, timezone.now())


@activity.defn
@scoped_temporal()
@close_db_connections
async def score_anomaly_insight_activity(input: ScoreInsightInput) -> ScoreInsightResult:
    async with Heartbeater():
        return await database_sync_to_async(run_insight, thread_sensitive=False)(input, timezone.now())


@activity.defn
@scoped_temporal()
@close_db_connections
async def capture_anomaly_scoring_tick_activity(result: AnomalyScoringTickResult) -> None:
    await database_sync_to_async(capture_tick, thread_sensitive=False)(result)


@workflow.defn(name=TICK_WORKFLOW_NAME)
class AnomalyScoringTickWorkflow:
    @workflow.run
    async def run(self, inputs: AnomalyScoringTickInput) -> AnomalyScoringTickResult:
        started = workflow.now()
        try:
            plan = await workflow.execute_activity(
                plan_anomaly_scoring_tick_activity,
                inputs,
                start_to_close_timeout=_PLAN_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except ActivityError as error:
            # Without this event, a failed tick looks like a missing tick. The workflow still fails.
            plan_ms = round((workflow.now() - started).total_seconds() * 1000)
            await self._capture(
                AnomalyScoringTickResult(
                    enabled=True,
                    duration_ms=plan_ms,
                    plan_ms=plan_ms,
                    plan_failed=True,
                    plan_error=plan_error_class(error),
                )
            )
            raise
        plan_ms = round((workflow.now() - started).total_seconds() * 1000)
        if not plan.enabled:
            return AnomalyScoringTickResult()

        statuses: Counter[str] = Counter()
        errored = 0
        events = 0
        deferred = 0
        started_picks: list[InsightPick] = []
        concurrency = max(1, plan.max_concurrency)
        for index in range(0, len(plan.picks), concurrency):
            if workflow.now() - started >= TICK_BUDGET:
                deferred = len(plan.picks) - index
                break
            batch = plan.picks[index : index + concurrency]
            started_picks.extend(batch)
            results = await asyncio.gather(
                *(
                    workflow.execute_activity(
                        score_anomaly_insight_activity,
                        ScoreInsightInput(pick=pick, limits=plan.limits),
                        start_to_close_timeout=_INSIGHT_TIMEOUT,
                        heartbeat_timeout=_INSIGHT_HEARTBEAT_TIMEOUT,
                        # A failed insight waits for its cooldown and a later tick, not a retry in this one.
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )
                    for pick in batch
                ),
                return_exceptions=True,
            )
            for outcome in results:
                if isinstance(outcome, BaseException):
                    errored += 1
                    continue
                statuses[outcome.status] += 1
                events += outcome.events
            # More queries add load to a full cluster. The picks in flight finish, and no new pick starts.
            if statuses[STATUS_AT_CAPACITY]:
                break

        result = AnomalyScoringTickResult(
            enabled=True,
            candidates=plan.candidates,
            picked=len(started_picks),
            statuses=dict(statuses),
            errored=errored,
            events=events,
            duration_ms=round((workflow.now() - started).total_seconds() * 1000),
            deferred=deferred,
            queries=sum(pick.query_cost for pick in started_picks),
            skipped_for_budget=plan.skipped_for_budget,
            stopped_at_capacity=statuses[STATUS_AT_CAPACITY] > 0,
            run_train=sum(pick.run == ScoringRun.TRAIN for pick in started_picks),
            run_score=sum(pick.run == ScoringRun.SCORE for pick in started_picks),
            picked_score=plan.picked_score,
            picked_train=plan.picked_train,
            scored_stale_model=plan.scored_stale_model,
            train_backlog_soft=plan.train_backlog_soft,
            train_backlog_hard=plan.train_backlog_hard,
            active=plan.active,
            active_reasons=plan.active_reasons,
            enrolled_teams=plan.enrolled_teams,
            enrolled_organizations=plan.enrolled_organizations,
            plan_ms=plan_ms,
            teams_planned=plan.teams_planned,
            teams_skipped=plan.teams_skipped,
        )
        await self._capture(result)
        return result

    async def _capture(self, result: AnomalyScoringTickResult) -> None:
        await workflow.execute_activity(
            capture_anomaly_scoring_tick_activity,
            result,
            start_to_close_timeout=_CAPTURE_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
