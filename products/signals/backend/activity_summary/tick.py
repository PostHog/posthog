"""The scheduled activity summary tick: a Temporal workflow that drains the queue of due (team, user) pairs.

The `activity-summary` flag payload holds every lever, and a missing or malformed payload turns the
tick off. The pair activity calls `update_activity_summary`, then queues the embedding and the event.
"""

import asyncio
import datetime
import dataclasses
from collections import Counter
from typing import Any

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
    CALLED_MODEL_STATUSES,
    MAX_SKIP_BACKOFF,
    MAX_VERSIONS,
    VIEW_UPDATE_INTERVAL,
    ActivitySummaryUpdate,
    UpdateAfterModelCallError,
    UpdateStatus,
    record_update_exception,
    update_activity_summary,
)
from products.signals.backend.activity_summary.prompt import PROMPT_VERSION
from products.signals.backend.activity_summary.queue import (
    TRIGGERS,
    VIEW_TRIGGERS,
    ActivitySummaryPair,
    ActivitySummaryTierStats,
    daily_usage,
    enrollment,
    feed_queue,
    is_team_enrolled_for_generation,
    max_update_cost_usd,
    select_pairs,
    sync_pair_state,
)
from products.signals.backend.activity_summary.render import DEFAULT_LIMITS, RENDER_VERSION, RenderLimits
from products.signals.backend.activity_summary.summaries import DEFAULT_MODEL, PIPELINE_DISTINCT_ID
from products.signals.backend.models import UserActivitySummary
from products.signals.backend.report_embeddings import EMBEDDING_PRODUCT

logger = structlog.get_logger(__name__)

TICK_WORKFLOW_NAME = "activity-summary-tick"
EMBEDDING_DOCUMENT_TYPE = "activity_summary"
EMBEDDING_RENDERING = "summary_text"
# Where a summary came from: the tick, or a build as of a past date.
SOURCE_LIVE = "live"

# Stop reasons of a tick. Null when the tick updated every due pair.
STOP_MAX_PAIRS_PER_TICK = "max_pairs_per_tick"
STOP_MAX_PAIRS_PER_DAY = "max_pairs_per_day"
STOP_MAX_COST_USD_PER_DAY = "max_cost_usd_per_day"
STOP_GATEWAY_NOT_CONFIGURED = "gateway_not_configured"
# Due pairs are left, but each organization with due pairs already has its share of the tick.
STOP_MAX_ORG_SHARE = "max_org_share"
STOP_ERROR_RATE = "error_rate"

# The circuit breaker waits for this many model calls, so a few early failures do not stop the tick.
_MIN_ERROR_RATE_SAMPLE = 10

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
class EnrollmentCounts:
    qualifying_organizations: int = 0
    enrolled_organizations: int = 0
    enrolled_teams: int = 0


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
    # Defaults, so a plan that a workflow history recorded before these fields existed still decodes.
    limits: RenderLimits = DEFAULT_LIMITS
    rebuild_before: datetime.datetime | None = None
    max_versions: int = MAX_VERSIONS
    max_error_rate: float = 1.0
    max_skip_backoff_hours: float = MAX_SKIP_BACKOFF.total_seconds() / 3600
    tiers: list[ActivitySummaryTierStats] = dataclasses.field(default_factory=list)
    enrollment: EnrollmentCounts = dataclasses.field(default_factory=EnrollmentCounts)
    view_update_interval_hours: float = VIEW_UPDATE_INTERVAL.total_seconds() / 3600
    due_by_trigger: dict[str, int] = dataclasses.field(default_factory=dict)


@frozen
class ActivitySummaryPairInput:
    team_id: int
    user_id: int
    min_units: int
    min_update_interval_hours: float
    emit_embeddings: bool
    capture_events: bool
    # Defaults, so a pair input that a tick queued before these fields existed still decodes.
    limits: RenderLimits = DEFAULT_LIMITS
    rebuild_before: datetime.datetime | None = None
    # Has a default, so the pair input of a workflow in flight during a deploy still decodes.
    max_versions: int = MAX_VERSIONS
    max_skip_backoff_hours: float = MAX_SKIP_BACKOFF.total_seconds() / 3600
    # Why the queue picked the pair. A view trigger waits `view_update_interval_hours` after a good update.
    trigger: str | None = None
    view_update_interval_hours: float | None = None


@frozen
class ActivitySummaryPairResult:
    status: str
    cost_usd: float | None
    called_model: bool
    # Has a default, so the result of a pair activity in flight during a deploy still decodes.
    new_summary: bool = False


@frozen
class ActivitySummaryTickResult:
    enabled: bool = False
    candidates: int = 0
    picked: int = 0
    statuses: dict[str, int] | None = None
    errored: int = 0
    cost_usd: float = 0.0
    stop_reason: str | None = None
    tiers: list[ActivitySummaryTierStats] = dataclasses.field(default_factory=list)
    enrollment: EnrollmentCounts = dataclasses.field(default_factory=EnrollmentCounts)
    # Successful updates that made a pair's first summary, and successful updates of an existing summary.
    new_builds: int = 0
    refresh_builds: int = 0
    # Due pairs at the start of the tick, per trigger.
    due_by_trigger: dict[str, int] = dataclasses.field(default_factory=dict)


def plan_tick(limit: int | None, now: datetime.datetime) -> ActivitySummaryTickPlan:
    config = read_config()
    gateway_missing = config.enabled and not openai_gateway_configured()
    if gateway_missing:
        # Every pair would fail on the same missing gateway, so the tick runs none.
        logger.warning("activity_summary_tick_gateway_not_configured")
    enabled = config.enabled and not gateway_missing
    # One enrollment read serves the feed, the selection and the counts.
    enrolled = enrollment(config)
    counts = EnrollmentCounts(
        qualifying_organizations=len(enrolled.qualifying_organization_ids),
        enrolled_organizations=len(enrolled.organization_ids),
        enrolled_teams=len(enrolled.team_ids),
    )
    logger.info("activity_summary_enrollment_read", **dataclasses.asdict(counts))
    if config.enabled:
        # The cursors move even when a cap stops the tick, so new rows do not pile up behind them.
        feed_queue(config, now, enrolled.team_ids)
    usage = daily_usage(now) if enabled else None
    updates_left = max(0, config.max_pairs_per_day - usage.updates) if usage else 0
    cost_left = max(0.0, config.max_cost_usd_per_day - usage.cost_usd) if usage else 0.0
    tick_limit = limit or config.max_pairs_per_tick
    selection = select_pairs(config, now, tick_limit, enrolled.team_ids) if updates_left and cost_left else None
    pairs = selection.pairs if selection else []
    due_pairs = selection.due_pairs if selection else 0

    stop_reason: str | None = None
    if gateway_missing:
        stop_reason = STOP_GATEWAY_NOT_CONFIGURED
    elif enabled and not updates_left:
        stop_reason = STOP_MAX_PAIRS_PER_DAY
    elif enabled and not cost_left:
        stop_reason = STOP_MAX_COST_USD_PER_DAY
    elif due_pairs > len(pairs):
        stop_reason = STOP_MAX_PAIRS_PER_TICK if len(pairs) >= tick_limit else STOP_MAX_ORG_SHARE
    return ActivitySummaryTickPlan(
        enabled=enabled,
        pairs=pairs,
        candidates=due_pairs,
        updates_left=updates_left,
        cost_left_usd=cost_left,
        max_update_cost_usd=max_update_cost_usd(config.limits),
        max_concurrency=config.max_concurrency,
        min_units=config.min_units,
        min_update_interval_hours=config.min_update_interval_hours,
        view_update_interval_hours=config.view_update_interval_hours,
        emit_embeddings=config.emit_embeddings,
        capture_events=config.capture_events,
        limits=config.limits,
        max_error_rate=config.max_error_rate,
        max_skip_backoff_hours=config.max_skip_backoff_hours,
        tiers=selection.tiers if selection else [],
        due_by_trigger=selection.due_by_trigger if selection else {},
        enrollment=counts,
        stop_reason=stop_reason,
        rebuild_before=config.rebuild_before,
        max_versions=config.max_versions,
    )


def emit_summary_embedding(
    team_id: int,
    *,
    content: str,
    document_type: str,
    document_id: str,
    timestamp: datetime.datetime,
    metadata: dict[str, Any],
) -> None:
    # Deferred so importing the tick does not load the Kafka and ClickHouse chain behind the producer.
    from posthog.api.embedding_worker import emit_embedding_request  # noqa: PLC0415

    emit_embedding_request(
        content=content,
        team_id=team_id,
        product=EMBEDDING_PRODUCT,
        document_type=document_type,
        rendering=EMBEDDING_RENDERING,
        document_id=document_id,
        # The models of the report embeddings, so both share one vector space.
        models=[model.value for model in EmbeddingModelName],
        timestamp=timestamp,
        metadata=metadata,
    )


def _emit_embedding(team_id: int, user_id: int) -> None:
    stored = UserActivitySummary.objects.for_team(team_id).filter(user_id=user_id).first()
    if stored is None or not stored.summary_text or stored.generated_at is None:
        return
    emit_summary_embedding(
        team_id,
        content=stored.summary_text,
        document_type=EMBEDDING_DOCUMENT_TYPE,
        # One vector per user per day, so an analysis can read the vector a user had on a given day.
        document_id=f"{user_id}:{stored.generated_at.date().isoformat()}",
        timestamp=stored.generated_at,
        metadata={
            "prompt_version": stored.prompt_version,
            "render_version": stored.render_version,
            "model": stored.model,
        },
    )


def capture_generated(
    team_id: int, user_id: int, update: ActivitySummaryUpdate, trigger: str | None, *, source: str = SOURCE_LIVE
) -> None:
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
            "trigger": trigger,
            "source": source,
        },
        groups={"organization": str(team.organization_id), "project": str(team.uuid)},
    )


def _enrolled_at_dispatch(team_id: int) -> bool:
    # The flag can change between the plan and the pair, so the pair reads it again.
    team = Team.objects.select_related("organization").filter(id=team_id).first()
    return team is not None and is_team_enrolled_for_generation(read_config(), team)


def run_pair(input: ActivitySummaryPairInput, *, last_attempt: bool = True) -> ActivitySummaryPairResult:
    if not _enrolled_at_dispatch(input.team_id):
        return ActivitySummaryPairResult(
            status=UpdateStatus.SKIPPED_NOT_ENROLLED.value, cost_usd=None, called_model=False
        )
    interval_hours = input.min_update_interval_hours
    if input.trigger in VIEW_TRIGGERS and input.view_update_interval_hours is not None:
        interval_hours = input.view_update_interval_hours
    try:
        update = update_activity_summary(
            input.team_id,
            input.user_id,
            min_units=input.min_units,
            min_update_interval=datetime.timedelta(hours=interval_hours),
            limits=input.limits,
            rebuild_before=input.rebuild_before,
            max_versions=input.max_versions,
            max_skip_backoff=datetime.timedelta(hours=input.max_skip_backoff_hours),
        )
        called_model = update.status in CALLED_MODEL_STATUSES
    except Exception as error:
        if not last_attempt:
            raise
        logger.exception("activity_summary_update_failed", team_id=input.team_id, user_id=input.user_id)
        # Without a failed row and a backoff, the queue picks the same pair again on the next tick.
        update = record_update_exception(input.team_id, input.user_id, error)
        called_model = isinstance(error, UpdateAfterModelCallError)
    try:
        sync_pair_state(input.team_id, input.user_id)
    except Exception:
        # The pair stays due, so the next tick picks it, skips it as not eligible yet, and syncs it then.
        logger.exception("activity_summary_queue_sync_failed", team_id=input.team_id, user_id=input.user_id)
    if update.status == UpdateStatus.OK and input.emit_embeddings:
        try:
            _emit_embedding(input.team_id, input.user_id)
        except Exception:
            logger.exception("activity_summary_embedding_failed", team_id=input.team_id, user_id=input.user_id)
    if update.status in CALLED_MODEL_STATUSES and input.capture_events:
        try:
            capture_generated(input.team_id, input.user_id, update, input.trigger)
        except Exception:
            logger.exception("activity_summary_capture_failed", team_id=input.team_id, user_id=input.user_id)
    return ActivitySummaryPairResult(
        status=update.status.value,
        cost_usd=update.cost_usd,
        called_model=called_model,
        new_summary=update.new_summary,
    )


def capture_tick(result: ActivitySummaryTickResult) -> None:
    logger.info(
        "activity_summary_tick_finished",
        candidates=result.candidates,
        picked=result.picked,
        statuses=result.statuses,
        errored=result.errored,
        cost_usd=result.cost_usd,
        stop_reason=result.stop_reason,
        tiers=[dataclasses.asdict(tier) for tier in result.tiers],
        new_builds=result.new_builds,
        refresh_builds=result.refresh_builds,
        due_by_trigger=result.due_by_trigger,
        **dataclasses.asdict(result.enrollment),
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
            "new_builds": result.new_builds,
            "refresh_builds": result.refresh_builds,
            **{f"due_{trigger}": result.due_by_trigger.get(trigger, 0) for trigger in TRIGGERS},
            **dataclasses.asdict(result.enrollment),
            **{
                f"{tier.tier}_{name}": getattr(tier, name)
                for tier in result.tiers
                for name in ("due_pairs", "oldest_due_hours", "fresh_share")
            },
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
        builds: Counter[bool] = Counter()
        errored = 0
        cost = 0.0
        # Model calls of this tick and the calls among them that failed or raised, for the circuit breaker.
        calls = 0
        failures = 0
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
            # The pairs not attempted yet stay due with no backoff, so the next tick picks them.
            if calls >= _MIN_ERROR_RATE_SAMPLE and failures >= plan.max_error_rate * calls:
                stop_reason = STOP_ERROR_RATE
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
                            max_versions=plan.max_versions,
                            max_skip_backoff_hours=plan.max_skip_backoff_hours,
                            trigger=pair.trigger,
                            view_update_interval_hours=plan.view_update_interval_hours,
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
                    calls += 1
                    failures += 1
                    updates_left -= 1
                    cost += plan.max_update_cost_usd
                    continue
                statuses[outcome.status] += 1
                if outcome.status == UpdateStatus.OK:
                    builds[outcome.new_summary] += 1
                if outcome.called_model:
                    calls += 1
                    failures += outcome.status == UpdateStatus.FAILED
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
            tiers=plan.tiers,
            enrollment=plan.enrollment,
            new_builds=builds[True],
            refresh_builds=builds[False],
            due_by_trigger=plan.due_by_trigger,
        )
        await workflow.execute_activity(
            capture_activity_summary_tick_activity,
            result,
            start_to_close_timeout=datetime.timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        return result
