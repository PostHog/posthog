"""The scheduled anomaly scoring tick: a Temporal workflow that scores the due watched insights.

The `anomaly-scoring` flag payload holds every lever, and a missing or malformed payload turns the
tick off. Each insight activity scores one insight and writes its new buckets as `$anomaly_score` events.
"""

import asyncio
import datetime
from collections import Counter

from django.conf import settings
from django.utils import timezone

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.dataclasses import frozen
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
from products.signals.backend.anomaly_scores.queue import (
    ATTEMPT_COOLDOWN,
    UNSUPPORTED_COOLDOWN,
    InsightPick,
    mark_attempted,
    select_insights,
)
from products.signals.backend.anomaly_scores.scoring import UnsupportedInsightError, score_insight
from products.signals.backend.anomaly_scores.selection import parse_selection_config

logger = structlog.get_logger(__name__)

TICK_WORKFLOW_NAME = "anomaly-scoring-tick"

STATUS_SCORED = "scored"
# Scored, with no completed bucket newer than the ones already written.
STATUS_UP_TO_DATE = "up_to_date"
STATUS_UNSUPPORTED = "unsupported"
STATUS_MISSING = "missing"

_PLAN_TIMEOUT = datetime.timedelta(minutes=2)
# The scoring query times out at 60 seconds. The rest is detection and the capture request.
_INSIGHT_TIMEOUT = datetime.timedelta(minutes=3)
_INSIGHT_HEARTBEAT_TIMEOUT = datetime.timedelta(minutes=1)


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


@frozen
class ScoreInsightInput:
    pick: InsightPick
    limits: ScoringLimits = DEFAULT_LIMITS


@frozen
class ScoreInsightResult:
    status: str
    events: int


@frozen
class AnomalyScoringTickResult:
    enabled: bool = False
    candidates: int = 0
    picked: int = 0
    statuses: dict[str, int] | None = None
    errored: int = 0
    events: int = 0


def plan_tick(limit: int | None, now: datetime.datetime) -> AnomalyScoringTickPlan:
    # One read, so the scoring and selection levers come from the same payload.
    payload = read_payload()
    config = read_config(payload)
    if not config.enabled:
        return AnomalyScoringTickPlan(enabled=False, picks=[], candidates=0, max_concurrency=config.max_concurrency)
    selection = select_insights(config, parse_selection_config(payload), now, limit or config.max_insights_per_tick)
    return AnomalyScoringTickPlan(
        enabled=True,
        picks=selection.picks,
        candidates=selection.candidates,
        max_concurrency=config.max_concurrency,
        limits=config.limits,
    )


def run_insight(input: ScoreInsightInput, now: datetime.datetime) -> ScoreInsightResult:
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
    try:
        scores = score_insight(
            insight,
            team,
            now=now,
            # Every series is filtered again on its own newest bucket below. A new series gets up to the backfill cap.
            after=min(pick.scored_through.values()) if pick.scored_through else None,
            limits=input.limits,
        )
    except UnsupportedInsightError as error:
        logger.info("anomaly_scoring_insight_unsupported", insight_id=pick.insight_id, reason=str(error))
        mark_attempted(pick.insight_id, UNSUPPORTED_COOLDOWN)
        return ScoreInsightResult(status=STATUS_UNSUPPORTED, events=0)
    events = score_events(
        team_id=team.id, insight_id=insight.id, scores=scores, scored_through=pick.scored_through, scored_at=now
    )
    emit(team, events)
    return ScoreInsightResult(status=STATUS_SCORED if events else STATUS_UP_TO_DATE, events=len(events))


def capture_tick(result: AnomalyScoringTickResult) -> None:
    logger.info(
        "anomaly_scoring_tick_finished",
        candidates=result.candidates,
        picked=result.picked,
        statuses=result.statuses,
        errored=result.errored,
        events=result.events,
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
        concurrency = max(1, plan.max_concurrency)
        for index in range(0, len(plan.picks), concurrency):
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
                    for pick in plan.picks[index : index + concurrency]
                ),
                return_exceptions=True,
            )
            for outcome in results:
                if isinstance(outcome, BaseException):
                    errored += 1
                    continue
                statuses[outcome.status] += 1
                events += outcome.events

        result = AnomalyScoringTickResult(
            enabled=True,
            candidates=plan.candidates,
            picked=len(plan.picks),
            statuses=dict(statuses),
            errored=errored,
            events=events,
        )
        await workflow.execute_activity(
            capture_anomaly_scoring_tick_activity,
            result,
            start_to_close_timeout=datetime.timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        return result
