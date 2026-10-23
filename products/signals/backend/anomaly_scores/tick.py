"""The scheduled anomaly scoring tick: a Temporal workflow that scores the due watched insights.

The `anomaly-scoring` flag payload holds every lever, and a missing or malformed payload turns the
tick off. Each insight activity scores one insight and writes its new buckets as `$anomaly_score` events.
"""

import time
import asyncio
import datetime
from collections import Counter

from django.conf import settings
from django.utils import timezone

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

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
from products.signals.backend.anomaly_scores.config import (
    ANOMALY_SCORING_FLAG_DISTINCT_ID,
    DEFAULT_LIMITS,
    ScoringLimits,
    read_config,
    read_payload,
)
from products.signals.backend.anomaly_scores.emission import emit, score_events
from products.signals.backend.anomaly_scores.metrics import record_candidates, record_pick
from products.signals.backend.anomaly_scores.queue import (
    ATTEMPT_COOLDOWN,
    SKIP_COOLDOWN,
    InsightPick,
    mark_attempted,
    select_insights,
)
from products.signals.backend.anomaly_scores.scoring import (
    SCORING_QUERY_BUDGET_SECONDS,
    UnsupportedInsightError,
    score_insight,
)
from products.signals.backend.anomaly_scores.selection import parse_selection_config

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
# Any other failure. The activity raises it, and the workflow counts it as `errored`.
STATUS_ERRORED = "errored"

_PLAN_TIMEOUT = datetime.timedelta(minutes=2)
# All the scoring queries of one insight stop within their budget. The rest is detection, the capture request,
# and the failure classification. A query timeout must reach the classification, so that it gets the 1 day cooldown.
_INSIGHT_TIMEOUT = datetime.timedelta(seconds=SCORING_QUERY_BUDGET_SECONDS) + datetime.timedelta(seconds=90)
_INSIGHT_HEARTBEAT_TIMEOUT = datetime.timedelta(minutes=1)
_CAPTURE_TIMEOUT = datetime.timedelta(minutes=1)
# No batch of insights starts after this time. The picks that are left wait for a later tick.
TICK_BUDGET = datetime.timedelta(minutes=10)
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


@frozen
class ScoreInsightInput:
    pick: InsightPick
    limits: ScoringLimits = DEFAULT_LIMITS


@frozen
class ScoreInsightResult:
    status: str
    events: int
    series: int = 0


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


def plan_tick(limit: int | None, now: datetime.datetime) -> AnomalyScoringTickPlan:
    # One read, so the scoring and selection levers come from the same payload.
    payload = read_payload()
    config = read_config(payload)
    if not config.enabled:
        return AnomalyScoringTickPlan(enabled=False, picks=[], candidates=0, max_concurrency=config.max_concurrency)
    selection = select_insights(config, parse_selection_config(payload), now, limit or config.max_insights_per_tick)
    record_candidates(selection.candidates)
    return AnomalyScoringTickPlan(
        enabled=True,
        picks=selection.picks,
        candidates=selection.candidates,
        max_concurrency=config.max_concurrency,
        limits=config.limits,
        skipped_for_budget=selection.skipped_for_budget,
    )


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
        record_pick(status=status or STATUS_ERRORED, interval=interval, duration_ms=duration_ms, events=0)
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
    )
    record_pick(status=result.status, interval=interval, duration_ms=duration_ms, events=result.events)
    return result


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
    scores = score_insight(
        insight,
        team,
        now=now,
        # Every series is filtered again on its own newest bucket below. A new series gets up to the backfill cap.
        after=min(pick.scored_through.values()) if pick.scored_through else None,
        limits=input.limits,
    )
    events = score_events(
        team_id=team.id, insight_id=insight.id, scores=scores, scored_through=pick.scored_through, scored_at=now
    )
    emit(team, events)
    return ScoreInsightResult(
        status=STATUS_SCORED if events else STATUS_UP_TO_DATE, events=len(events), series=len(scores.series)
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
        plan = await workflow.execute_activity(
            plan_anomaly_scoring_tick_activity,
            inputs,
            start_to_close_timeout=_PLAN_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
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
        )
        await workflow.execute_activity(
            capture_anomaly_scoring_tick_activity,
            result,
            start_to_close_timeout=_CAPTURE_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        return result
