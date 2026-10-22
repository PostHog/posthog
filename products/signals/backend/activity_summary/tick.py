"""The scheduled activity summary tick: a Temporal workflow that drains the queue of due (team, user) pairs.

The `activity-summary` flag payload holds every lever, and a missing or malformed payload turns the
tick off. The pair activity calls `update_activity_summary`, then queues the embedding and the event.
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
from posthog.llm.gateway_client import openai_gateway_configured
from posthog.models import Team
from posthog.ph_client import ph_background_capture
from posthog.schema_enums import EmbeddingModelName
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.signals.backend.activity_summary.config import read_config
from products.signals.backend.activity_summary.logic import (
    ActivitySummaryUpdate,
    UpdateAfterModelCallError,
    UpdateStatus,
    record_update_exception,
    update_activity_summary,
)
from products.signals.backend.activity_summary.prompt import PROMPT_VERSION
from products.signals.backend.activity_summary.queue import (
    ActivitySummaryPair,
    daily_usage,
    max_update_cost_usd,
    select_pairs,
)
from products.signals.backend.activity_summary.render import DEFAULT_LIMITS, RENDER_VERSION, RenderLimits
from products.signals.backend.activity_summary.summaries import DEFAULT_MODEL, PIPELINE_DISTINCT_ID
from products.signals.backend.models import UserActivitySummary
from products.signals.backend.report_embeddings import EMBEDDING_PRODUCT

logger = structlog.get_logger(__name__)

TICK_WORKFLOW_NAME = "activity-summary-tick"
EMBEDDING_DOCUMENT_TYPE = "activity_summary"
EMBEDDING_RENDERING = "summary_text"

# Stop reasons of a tick. Null when the tick updated every due pair.
STOP_MAX_PAIRS_PER_TICK = "max_pairs_per_tick"
STOP_MAX_PAIRS_PER_DAY = "max_pairs_per_day"
STOP_MAX_COST_USD_PER_DAY = "max_cost_usd_per_day"
STOP_GATEWAY_NOT_CONFIGURED = "gateway_not_configured"

_PLAN_TIMEOUT = datetime.timedelta(minutes=5)
# One model call has a 120 second request timeout and one retry on a malformed answer.
_PAIR_TIMEOUT = datetime.timedelta(minutes=5)
_PAIR_HEARTBEAT_TIMEOUT = datetime.timedelta(minutes=1)
# An attempt that raises is retried. The last attempt records the exception as a failed update instead.
_PAIR_RETRY_POLICY = RetryPolicy(maximum_attempts=2, initial_interval=datetime.timedelta(seconds=10))


@frozen
class ActivitySummaryTickInput:
    # A manual run can override the per-tick cap of the flag.
    limit: int | None = None


@frozen
class ActivitySummaryTickPlan:
    enabled: bool
    pairs: list[ActivitySummaryPair]
    candidates: int
    # Updates and cost left today, from the stored rows at the start of the tick.
    updates_left: int
    cost_left_usd: float
    max_update_cost_usd: float
    max_concurrency: int
    min_units: int
    min_update_interval_hours: float
    emit_embeddings: bool
    capture_events: bool
    stop_reason: str | None
    # A default, so a plan that a workflow history recorded before this field existed still decodes.
    limits: RenderLimits = DEFAULT_LIMITS
    rebuild_before: datetime.datetime | None = None


@frozen
class ActivitySummaryPairInput:
    team_id: int
    user_id: int
    min_units: int
    min_update_interval_hours: float
    emit_embeddings: bool
    capture_events: bool
    # A default, so a pair input that a tick queued before this field existed still decodes.
    limits: RenderLimits = DEFAULT_LIMITS
    rebuild_before: datetime.datetime | None = None


@frozen
class ActivitySummaryPairResult:
    status: str
    cost_usd: float | None
    called_model: bool


@frozen
class ActivitySummaryTickResult:
    enabled: bool = False
    candidates: int = 0
    picked: int = 0
    statuses: dict[str, int] | None = None
    errored: int = 0
    cost_usd: float = 0.0
    stop_reason: str | None = None


def plan_tick(limit: int | None, now: datetime.datetime) -> ActivitySummaryTickPlan:
    config = read_config()
    gateway_missing = config.enabled and not openai_gateway_configured()
    if gateway_missing:
        # Every pair would fail on the same missing gateway, so the tick runs none.
        logger.warning("activity_summary_tick_gateway_not_configured")
    enabled = config.enabled and not gateway_missing
    usage = daily_usage(now) if enabled else None
    updates_left = max(0, config.max_pairs_per_day - usage.updates) if usage else 0
    cost_left = max(0.0, config.max_cost_usd_per_day - usage.cost_usd) if usage else 0.0
    tick_limit = limit or config.max_pairs_per_tick
    # One more than the cut, to tell a full queue from a queue the cut emptied.
    due = select_pairs(config, now, tick_limit + 1) if updates_left and cost_left else []

    stop_reason: str | None = None
    if gateway_missing:
        stop_reason = STOP_GATEWAY_NOT_CONFIGURED
    elif enabled and not updates_left:
        stop_reason = STOP_MAX_PAIRS_PER_DAY
    elif enabled and not cost_left:
        stop_reason = STOP_MAX_COST_USD_PER_DAY
    elif len(due) > tick_limit:
        stop_reason = STOP_MAX_PAIRS_PER_TICK
    return ActivitySummaryTickPlan(
        enabled=enabled,
        pairs=due[:tick_limit],
        candidates=len(due),
        updates_left=updates_left,
        cost_left_usd=cost_left,
        max_update_cost_usd=max_update_cost_usd(config.limits),
        max_concurrency=config.max_concurrency,
        min_units=config.min_units,
        min_update_interval_hours=config.min_update_interval_hours,
        emit_embeddings=config.emit_embeddings,
        capture_events=config.capture_events,
        limits=config.limits,
        stop_reason=stop_reason,
        rebuild_before=config.rebuild_before,
    )


def _emit_embedding(team_id: int, user_id: int) -> None:
    # Deferred so importing the tick does not load the Kafka and ClickHouse chain behind the producer.
    from posthog.api.embedding_worker import emit_embedding_request  # noqa: PLC0415

    stored = UserActivitySummary.objects.for_team(team_id).filter(user_id=user_id).first()
    if stored is None or not stored.summary_text or stored.generated_at is None:
        return
    emit_embedding_request(
        content=stored.summary_text,
        team_id=team_id,
        product=EMBEDDING_PRODUCT,
        document_type=EMBEDDING_DOCUMENT_TYPE,
        rendering=EMBEDDING_RENDERING,
        # One vector per user per day, so an analysis can read the vector a user had on a given day.
        document_id=f"{user_id}:{stored.generated_at.date().isoformat()}",
        # The models of the report embeddings, so both share one vector space.
        models=[model.value for model in EmbeddingModelName],
        timestamp=stored.generated_at,
        metadata={
            "prompt_version": stored.prompt_version,
            "render_version": stored.render_version,
            "model": stored.model,
        },
    )


def _capture_generated(team_id: int, user_id: int, update: ActivitySummaryUpdate) -> None:
    team = Team.objects.only("uuid", "organization_id").get(id=team_id)
    # Counts and accounting only. The summary and the rendered input are user content.
    ph_background_capture()(
        distinct_id=PIPELINE_DISTINCT_ID,
        event="activity summary generated",
        properties={
            "team_id": team_id,
            "user_id": user_id,
            "deployment": settings.CLOUD_DEPLOYMENT,
            "status": update.status.value,
            "error": update.error,
            "model": DEFAULT_MODEL,
            "prompt_version": PROMPT_VERSION,
            "render_version": RENDER_VERSION,
            "tokens_in": update.tokens_in,
            "tokens_out": update.tokens_out,
            "cost_usd": update.cost_usd,
            "latency_ms": update.latency_ms,
            "inputs_used": update.inputs_used,
            "rebuilt": update.rebuilt,
        },
        groups={"organization": str(team.organization_id), "project": str(team.uuid)},
    )


def run_pair(input: ActivitySummaryPairInput, *, last_attempt: bool = True) -> ActivitySummaryPairResult:
    try:
        update = update_activity_summary(
            input.team_id,
            input.user_id,
            min_units=input.min_units,
            min_update_interval=datetime.timedelta(hours=input.min_update_interval_hours),
            limits=input.limits,
            rebuild_before=input.rebuild_before,
        )
        called_model = update.status in (UpdateStatus.OK, UpdateStatus.FAILED)
    except Exception as error:
        if not last_attempt:
            raise
        logger.exception("activity_summary_update_failed", team_id=input.team_id, user_id=input.user_id)
        # Without a failed row and a backoff, the queue picks the same pair again on the next tick.
        update = record_update_exception(input.team_id, input.user_id, error)
        called_model = isinstance(error, UpdateAfterModelCallError)
    if update.status == UpdateStatus.OK and input.emit_embeddings:
        try:
            _emit_embedding(input.team_id, input.user_id)
        except Exception:
            logger.exception("activity_summary_embedding_failed", team_id=input.team_id, user_id=input.user_id)
    if update.status in (UpdateStatus.OK, UpdateStatus.FAILED) and input.capture_events:
        try:
            _capture_generated(input.team_id, input.user_id, update)
        except Exception:
            logger.exception("activity_summary_capture_failed", team_id=input.team_id, user_id=input.user_id)
    return ActivitySummaryPairResult(status=update.status.value, cost_usd=update.cost_usd, called_model=called_model)


def capture_tick(result: ActivitySummaryTickResult) -> None:
    logger.info(
        "activity_summary_tick_finished",
        candidates=result.candidates,
        picked=result.picked,
        statuses=result.statuses,
        errored=result.errored,
        cost_usd=result.cost_usd,
        stop_reason=result.stop_reason,
    )
    ph_background_capture()(
        distinct_id=PIPELINE_DISTINCT_ID,
        event="activity summary tick",
        properties={
            "deployment": settings.CLOUD_DEPLOYMENT,
            "candidates": result.candidates,
            "picked": result.picked,
            **{f"status_{status}": count for status, count in (result.statuses or {}).items()},
            "errored": result.errored,
            "cost_usd": result.cost_usd,
            "stop_reason": result.stop_reason,
        },
    )


@activity.defn
@scoped_temporal()
@close_db_connections
async def plan_activity_summary_tick_activity(input: ActivitySummaryTickInput) -> ActivitySummaryTickPlan:
    return await database_sync_to_async(plan_tick, thread_sensitive=False)(input.limit, timezone.now())


@activity.defn
@scoped_temporal()
@close_db_connections
async def update_activity_summary_pair_activity(input: ActivitySummaryPairInput) -> ActivitySummaryPairResult:
    last_attempt = activity.info().attempt >= _PAIR_RETRY_POLICY.maximum_attempts
    async with Heartbeater():
        return await database_sync_to_async(run_pair, thread_sensitive=False)(input, last_attempt=last_attempt)


@activity.defn
@scoped_temporal()
@close_db_connections
async def capture_activity_summary_tick_activity(result: ActivitySummaryTickResult) -> None:
    await database_sync_to_async(capture_tick, thread_sensitive=False)(result)


@workflow.defn(name=TICK_WORKFLOW_NAME)
class ActivitySummaryTickWorkflow:
    @workflow.run
    async def run(self, inputs: ActivitySummaryTickInput) -> ActivitySummaryTickResult:
        plan = await workflow.execute_activity(
            plan_activity_summary_tick_activity,
            inputs,
            start_to_close_timeout=_PLAN_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        if not plan.enabled:
            return ActivitySummaryTickResult(stop_reason=plan.stop_reason)

        statuses: Counter[str] = Counter()
        errored = 0
        cost = 0.0
        updates_left = plan.updates_left
        stop_reason = plan.stop_reason
        picked = 0
        concurrency = max(1, plan.max_concurrency)
        index = 0
        while index < len(plan.pairs):
            # A wave can pass the cost cap by at most one wave of updates at their highest cost.
            if updates_left <= 0:
                stop_reason = STOP_MAX_PAIRS_PER_DAY
                break
            if cost >= plan.cost_left_usd:
                stop_reason = STOP_MAX_COST_USD_PER_DAY
                break
            wave = plan.pairs[index : index + min(concurrency, updates_left)]
            index += len(wave)
            picked += len(wave)
            results = await asyncio.gather(
                *(
                    workflow.execute_activity(
                        update_activity_summary_pair_activity,
                        ActivitySummaryPairInput(
                            team_id=pair.team_id,
                            user_id=pair.user_id,
                            min_units=plan.min_units,
                            min_update_interval_hours=plan.min_update_interval_hours,
                            emit_embeddings=plan.emit_embeddings,
                            capture_events=plan.capture_events,
                            limits=plan.limits,
                            rebuild_before=plan.rebuild_before,
                        ),
                        start_to_close_timeout=_PAIR_TIMEOUT,
                        heartbeat_timeout=_PAIR_HEARTBEAT_TIMEOUT,
                        retry_policy=_PAIR_RETRY_POLICY,
                    )
                    for pair in wave
                ),
                return_exceptions=True,
            )
            for outcome in results:
                if isinstance(outcome, BaseException):
                    # The attempt can have called the model, so it counts at the highest cost.
                    errored += 1
                    updates_left -= 1
                    cost += plan.max_update_cost_usd
                    continue
                statuses[outcome.status] += 1
                if outcome.called_model:
                    updates_left -= 1
                    cost += plan.max_update_cost_usd if outcome.cost_usd is None else outcome.cost_usd

        result = ActivitySummaryTickResult(
            enabled=True,
            candidates=plan.candidates,
            picked=picked,
            statuses=dict(statuses),
            errored=errored,
            cost_usd=cost,
            stop_reason=stop_reason,
        )
        await workflow.execute_activity(
            capture_activity_summary_tick_activity,
            result,
            start_to_close_timeout=datetime.timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        return result
