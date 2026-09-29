from datetime import date, datetime, timedelta
from functools import partial

from django.conf import settings
from django.db import transaction
from django.db.models import F, Min, Q
from django.utils import timezone

import structlog
import posthoganalytics
from celery import shared_task
from prometheus_client import Counter
from redis.exceptions import RedisError

from posthog.celery_queues import CeleryQueue
from posthog.clickhouse.client.execute import KillSwitchLevel, get_kill_switch_level
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.errors import CH_TRANSIENT_ERRORS
from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.scoping_audit import skip_team_scope_audit

from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    TargetType,
    create_notification,
)
from products.web_analytics.backend.achievements.definitions import (
    STAGE_COUNT,
    STREAK_ARM_CONTROL,
    TRACKS,
    AchievementScope,
    TrackDefinition,
)
from products.web_analytics.backend.achievements.evaluators import (
    EVALUATORS,
    INCREMENTAL_EVALUATORS,
    EvalContext,
    PriorProgress,
    TrackEvaluation,
)
from products.web_analytics.backend.models import (
    WebAnalyticsAchievementProgress,
    WebAnalyticsUserConfig,
    WebAnalyticsVisit,
)

logger = structlog.get_logger(__name__)

STREAK_CADENCE_FLAG = "web-analytics-streak-cadence"
ACHIEVEMENTS_FLAG = "web-analytics-achievements"
SWEEP_ACTIVE_WINDOW_DAYS = 7
RECOMPUTE_INTERVAL = timedelta(hours=20)
RECOMPUTE_EXPIRES_SECONDS = 5 * 60
RETRYABLE_ACHIEVEMENT_ERRORS = (ConcurrencyLimitExceeded, RedisError, *CH_TRANSIENT_ERRORS)
TEAM_QUERY_TRACK_KEYS = [str(track.key) for track in TRACKS.values() if track.evaluator_key in INCREMENTAL_EVALUATORS]

RECOMPUTE_RUNS = Counter(
    "web_analytics_achievements_recompute_total",
    "Background team recomputes of Web analytics achievements, by outcome.",
    labelnames=["outcome"],
)
SWEEP_ENQUEUED = Counter(
    "web_analytics_achievements_sweep_enqueued_total",
    "Team recomputes enqueued by the Web analytics achievements sweep.",
)


def team_local_today(team: Team) -> date:
    return datetime.now(team.timezone_info).date()


def streak_arm_for_user(user: User) -> str | None:
    if not user.distinct_id:
        return None
    try:
        variant = posthoganalytics.get_feature_flag(STREAK_CADENCE_FLAG, str(user.distinct_id))
    except Exception:
        return None
    return variant if isinstance(variant, str) else None


def _achievements_flag_enabled(distinct_id: str, org_id: str) -> bool:
    try:
        return bool(
            posthoganalytics.feature_enabled(
                ACHIEVEMENTS_FLAG,
                distinct_id,
                groups={"organization": org_id},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception as e:
        logger.warning("wa_achievements_flag_eval_failed", distinct_id=distinct_id, org_id=org_id, exc_info=True)
        capture_exception(e)
        return False


def _user_opted_out(team: Team, user: User) -> bool:
    return WebAnalyticsUserConfig.objects.for_team(team.id).filter(user_id=user.id, achievements_opt_out=True).exists()


def recompute_web_analytics_achievements_sync(
    team_id: int, user_id: int | None = None, cheap_only: bool = False
) -> None:
    """Recompute achievement progress for one scope. With `user_id`, only user-scoped tracks run;
    without it, only team-scoped tracks run (driven by the periodic sweep)."""
    team = Team.objects.get(id=team_id)
    today = team_local_today(team)
    user: User | None = None
    arm: str | None = None
    if user_id is not None:
        user = User.objects.get(id=user_id)
        arm = streak_arm_for_user(user)
        if arm == STREAK_ARM_CONTROL:
            return
    ctx = EvalContext(team=team, user=user, today=today, arm=arm)
    for track in TRACKS.values():
        if track.scope == AchievementScope.USER and user is None:
            continue
        if track.scope == AchievementScope.TEAM and user is not None:
            continue
        if cheap_only and track.evaluator_key in INCREMENTAL_EVALUATORS:
            continue
        _recompute_track(ctx, track)


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.ANALYTICS_LIMITED.value,
    expires=RECOMPUTE_EXPIRES_SECONDS,
    max_retries=0,
    soft_time_limit=120,
    time_limit=150,
)
@skip_team_scope_audit
def recompute_web_analytics_achievements(team_id: int, user_id: int | None = None) -> None:
    try:
        recompute_web_analytics_achievements_sync(team_id, user_id=user_id)
    except ConcurrencyLimitExceeded:
        RECOMPUTE_RUNS.labels(outcome="contention").inc()
        return
    except RETRYABLE_ACHIEVEMENT_ERRORS:
        RECOMPUTE_RUNS.labels(outcome="transient_error").inc()
        logger.warning("wa_achievements_recompute_transient_error", team_id=team_id, exc_info=True)
        return
    RECOMPUTE_RUNS.labels(outcome="ok").inc()


def ensure_team_progress(team: Team) -> None:
    ctx = EvalContext(team=team, user=None, today=team_local_today(team), arm=None)
    for track in TRACKS.values():
        if track.scope == AchievementScope.TEAM:
            get_or_create_progress(ctx, track)


def get_or_create_progress(ctx: EvalContext, track: TrackDefinition) -> WebAnalyticsAchievementProgress:
    user_id = ctx.user.id if (track.scope == AchievementScope.USER and ctx.user is not None) else None
    canonical_team_id = ctx.team.parent_team_id or ctx.team.id
    progress, _ = WebAnalyticsAchievementProgress.objects.for_team(ctx.team.id).get_or_create(
        team_id=canonical_team_id,
        user_id=user_id,
        track_key=str(track.key),
        defaults={"current_stage": 0, "progress_value": 0, "state": {}},
    )
    return progress


def is_due(progress: WebAnalyticsAchievementProgress) -> bool:
    return progress.last_computed_at is None or progress.last_computed_at <= timezone.now() - RECOMPUTE_INTERVAL


def persist_progress(
    progress: WebAnalyticsAchievementProgress,
    value: int,
    stage: int,
    state: dict,
    bump_last_computed_at: bool = True,
) -> None:
    progress.progress_value = value
    progress.current_stage = stage
    if bump_last_computed_at:
        progress.last_computed_at = timezone.now()
    progress.state = state
    progress.save()


def _last_visit_date_iso(ctx: EvalContext) -> str | None:
    if ctx.user is None:
        return None
    latest = (
        WebAnalyticsVisit.objects.for_team(ctx.team.id)
        .filter(user_id=ctx.user.id)
        .order_by("-visit_date")
        .values_list("visit_date", flat=True)
        .first()
    )
    return latest.isoformat() if latest else None


def evaluate_track(
    ctx: EvalContext, track: TrackDefinition, progress: WebAnalyticsAchievementProgress
) -> TrackEvaluation:
    incremental_evaluator = INCREMENTAL_EVALUATORS.get(track.evaluator_key)
    if incremental_evaluator is None:
        return TrackEvaluation(value=EVALUATORS[track.evaluator_key](ctx))
    checkpoint = (progress.state or {}).get("checkpoint")
    prior = PriorProgress(
        value=progress.progress_value,
        last_computed_at=progress.last_computed_at,
        checkpoint=checkpoint if isinstance(checkpoint, dict) else {},
    )
    return incremental_evaluator(ctx, prior)


def _recompute_track(ctx: EvalContext, track: TrackDefinition) -> None:
    progress = get_or_create_progress(ctx, track)
    if progress.current_stage >= len(track.stages):
        return
    if track.evaluator_key in INCREMENTAL_EVALUATORS and not is_due(progress):
        return
    try:
        evaluation = evaluate_track(ctx, track, progress)
    except RETRYABLE_ACHIEVEMENT_ERRORS:
        raise
    except Exception as e:
        logger.warning("wa_achievements_eval_failed", track=str(track.key), team_id=ctx.team.id, exc_info=True)
        capture_exception(e)
        return

    _apply_progress(ctx, track, progress, evaluation)


def _apply_progress(
    ctx: EvalContext,
    track: TrackDefinition,
    evaluated_progress: WebAnalyticsAchievementProgress,
    evaluation: TrackEvaluation,
) -> list[int]:
    with transaction.atomic():
        progress = (
            WebAnalyticsAchievementProgress.objects.for_team(ctx.team.id)
            .select_for_update()
            .get(pk=evaluated_progress.pk)
        )
        if evaluation.checkpoint is not None and progress.last_computed_at != evaluated_progress.last_computed_at:
            return []
        new_value = evaluation.value
        is_cumulative = track.evaluator_key != "streak"
        value = max(new_value, progress.progress_value) if is_cumulative else new_value
        arm = ctx.arm if track.is_experiment_track else None
        new_stage = max(progress.current_stage, track.stage_for_value(value, arm))

        state = dict(progress.state or {})
        unlocked_stages = dict(state.get("unlocked_stages", {}))
        pending_celebrations = list(state.get("pending_celebrations", []))
        newly_unlocked: list[int] = []
        if new_stage > progress.current_stage:
            now_iso = timezone.now().isoformat()
            for stage in range(progress.current_stage + 1, new_stage + 1):
                unlocked_stages[str(stage)] = now_iso
                pending_celebrations.append(stage)
                newly_unlocked.append(stage)
        state["unlocked_stages"] = unlocked_stages
        state["pending_celebrations"] = pending_celebrations
        if track.evaluator_key == "streak":
            state["streak"] = {"last_visit_date": _last_visit_date_iso(ctx)}
        if evaluation.checkpoint is not None:
            state["checkpoint"] = evaluation.checkpoint

        persist_progress(progress, value, new_stage, state)

        if newly_unlocked:
            transaction.on_commit(partial(_send_unlock_notifications, ctx, track, newly_unlocked))
    return newly_unlocked


def _send_unlock_notifications(ctx: EvalContext, track: TrackDefinition, stages: list[int]) -> None:
    org_id = str(ctx.team.organization_id)
    if track.scope == AchievementScope.USER and ctx.user is not None:
        if _user_opted_out(ctx.team, ctx.user) or not _achievements_flag_enabled(str(ctx.user.distinct_id), org_id):
            return
    elif not _achievements_flag_enabled(str(ctx.team.uuid), org_id):
        return
    for stage in stages:
        _send_unlock_notification(ctx, track, stage)


def _send_unlock_notification(ctx: EvalContext, track: TrackDefinition, stage: int) -> None:
    stage_name = track.stages[stage - 1].name
    if track.scope == AchievementScope.USER and ctx.user is not None:
        target_type, target_id = TargetType.USER, str(ctx.user.id)
    else:
        target_type, target_id = TargetType.TEAM, str(ctx.team.id)
    try:
        create_notification(
            NotificationData(
                team_id=ctx.team.id,
                notification_type=NotificationType.ACHIEVEMENT_UNLOCKED,
                title=f"Achievement unlocked: {stage_name}",
                body=f"You reached {stage_name} on the {track.display_name} track in Web analytics.",
                target_type=target_type,
                target_id=target_id,
                resource_type="web_analytics",
                # Keyed per track so unlocks on different tracks stay separate rows in the inbox
                # instead of collapsing into one grouped row (see `groupKey` on the client).
                resource_id=str(track.key),
                priority=Priority.NORMAL,
                source_url=f"/project/{ctx.team.id}/web?openAchievements={track.key.value}",
            )
        )
    except Exception as e:
        logger.warning("wa_achievements_notification_failed", track=str(track.key), exc_info=True)
        capture_exception(e)


def due_team_ids(limit: int) -> list[int]:
    active_since = timezone.now().date() - timedelta(days=SWEEP_ACTIVE_WINDOW_DAYS)
    active_team_ids = (
        WebAnalyticsVisit.objects.unscoped().filter(visit_date__gte=active_since).values("team_id").distinct()
    )
    return list(
        WebAnalyticsAchievementProgress.objects.unscoped()
        .filter(
            user__isnull=True,
            track_key__in=TEAM_QUERY_TRACK_KEYS,
            current_stage__lt=STAGE_COUNT,
            team_id__in=active_team_ids,
        )
        .filter(Q(last_computed_at__isnull=True) | Q(last_computed_at__lte=timezone.now() - RECOMPUTE_INTERVAL))
        .values("team_id")
        .annotate(oldest_computed_at=Min("last_computed_at"))
        .order_by(F("oldest_computed_at").asc(nulls_first=True), "team_id")
        .values_list("team_id", flat=True)[:limit]
    )


@shared_task(ignore_result=True)
@skip_team_scope_audit
def sweep_web_analytics_achievement_team_tracks() -> None:
    kill_switch_level = get_kill_switch_level()
    if kill_switch_level != KillSwitchLevel.OFF:
        logger.info("wa_achievements_sweep_skipped_kill_switch", level=kill_switch_level)
        return
    batch_size = settings.WEB_ANALYTICS_ACHIEVEMENTS_SWEEP_BATCH_SIZE
    if batch_size <= 0:
        return
    team_ids = due_team_ids(batch_size)
    for team_id in team_ids:
        recompute_web_analytics_achievements.delay(team_id)
    SWEEP_ENQUEUED.inc(len(team_ids))
    logger.info("wa_achievements_sweep_enqueued", count=len(team_ids))
