from datetime import date, datetime, timedelta
from functools import partial
from uuid import UUID

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

import structlog
import posthoganalytics
from celery import shared_task

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.scoping_audit import skip_team_scope_audit
from posthog.utils import safe_cache_delete

from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    TargetType,
    create_notification,
)
from products.web_analytics.backend.achievements.definitions import (
    STREAK_ARM_CONTROL,
    TRACKS,
    AchievementScope,
    TrackDefinition,
    TrackKey,
)
from products.web_analytics.backend.achievements.evaluators import EVALUATORS, EvalContext
from products.web_analytics.backend.models import (
    WebAnalyticsAchievementProgress,
    WebAnalyticsInteraction,
    WebAnalyticsUserConfig,
    WebAnalyticsVisit,
)

logger = structlog.get_logger(__name__)

RECOMPUTE_DEBOUNCE_TTL_SECONDS = 26 * 60 * 60
STREAK_CADENCE_FLAG = "web-analytics-streak-cadence"
ACHIEVEMENTS_FLAG = "web-analytics-achievements"
SWEEP_ACTIVE_WINDOW_DAYS = 7

# Tracks recompute at most once per team-local day. For the visit-driven tracks this is exact,
# because a day can only be added to a streak or a loyal-day count once. For the ClickHouse-backed
# tracks it is a cost gate. The two first-party interaction counters are the exception. They move
# when a user slices the dashboard or opens a recording, so they stay ungated.
INTRADAY_EVALUATOR_KEYS = {"data_events", "recordings_opened"}

INTERACTION_TRACKS: dict[str, TrackKey] = {
    WebAnalyticsInteraction.DATA: TrackKey.EXPLORER,
    WebAnalyticsInteraction.RECORDING: TrackKey.DETECTIVE,
}


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


def enqueue_recompute_web_analytics_achievements_debounced(team_id: int, user_id: int | None, today: date) -> bool:
    """Enqueue a recompute for this scope at most once per team-local day. Date-keyed (not a rolling
    24h TTL) so the first visit each day recomputes promptly, keeping streaks fresh. Fails open on a
    cache error so a Redis blip can't drop the visit signal."""
    scope = str(user_id) if user_id is not None else "team"
    debounce_key = f"wa_achievements_recompute:{team_id}:{scope}:{today.isoformat()}"
    try:
        claimed = cache.add(debounce_key, "1", timeout=RECOMPUTE_DEBOUNCE_TTL_SECONDS)
    except Exception as e:
        logger.warning("wa_achievements_debounce_cache_failure", team_id=team_id, exc_info=True)
        capture_exception(e)
        claimed = False
    else:
        if not claimed:
            return False
    try:
        recompute_web_analytics_achievements.delay(team_id, user_id=user_id)
    except Exception:
        if claimed:
            safe_cache_delete(debounce_key)
        raise
    return True


def _eval_context(team_id: int, user_id: int | None) -> EvalContext | None:
    """Build the evaluation context for one scope, or None for a control-arm user, who gets no
    achievements at all."""
    team = Team.objects.get(id=team_id)
    if user_id is None:
        return EvalContext(team=team, user=None, today=team_local_today(team), arm=None)
    user = User.objects.get(id=user_id)
    arm = streak_arm_for_user(user)
    if arm == STREAK_ARM_CONTROL:
        return None
    return EvalContext(team=team, user=user, today=team_local_today(team), arm=arm)


def recompute_web_analytics_achievements_sync(team_id: int, user_id: int | None = None) -> None:
    """Recompute achievement progress for one scope. With `user_id`, only user-scoped tracks run;
    without it, only team-scoped tracks run (driven by the periodic sweep)."""
    ctx = _eval_context(team_id, user_id)
    if ctx is None:
        return
    for track in TRACKS.values():
        if track.scope == AchievementScope.USER and ctx.user is None:
            continue
        if track.scope == AchievementScope.TEAM and ctx.user is not None:
            continue
        _recompute_track(ctx, track)


def recompute_interaction_track_sync(team_id: int, user_id: int, interaction_kind: str) -> None:
    """Recompute only the track an interaction feeds. This runs inline because the client re-reads
    the counter straight after, and because the counter is the one input that moves mid-day."""
    track_key = INTERACTION_TRACKS.get(interaction_kind)
    if track_key is None:
        return
    ctx = _eval_context(team_id, user_id)
    if ctx is None:
        return
    _recompute_track(ctx, TRACKS[track_key])


@shared_task(ignore_result=True)
@skip_team_scope_audit
def recompute_web_analytics_achievements(team_id: int, user_id: int | None = None) -> None:
    recompute_web_analytics_achievements_sync(team_id, user_id=user_id)


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


def is_due(ctx: EvalContext, progress: WebAnalyticsAchievementProgress) -> bool:
    if progress.last_computed_at is None:
        return True
    last_local_date = progress.last_computed_at.astimezone(ctx.team.timezone_info).date()
    return last_local_date < ctx.today


def persist_progress(
    progress: WebAnalyticsAchievementProgress,
    value: int,
    stage: int,
    state: dict,
    bump_last_computed_at: bool = True,
) -> None:
    """Write only the columns that moved, so a recompute that changes nothing costs no row rewrite."""
    update_fields: list[str] = []
    if progress.progress_value != value:
        progress.progress_value = value
        update_fields.append("progress_value")
    if progress.current_stage != stage:
        progress.current_stage = stage
        update_fields.append("current_stage")
    if (progress.state or {}) != state:
        progress.state = state
        update_fields.append("state")
    if bump_last_computed_at:
        progress.last_computed_at = timezone.now()
        update_fields.append("last_computed_at")
    if not update_fields:
        return
    progress.save(update_fields=[*update_fields, "updated_at"])


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


def _recompute_track(ctx: EvalContext, track: TrackDefinition) -> None:
    progress = get_or_create_progress(ctx, track)
    if progress.current_stage >= len(track.stages):
        return
    if track.evaluator_key not in INTRADAY_EVALUATOR_KEYS and not is_due(ctx, progress):
        return
    evaluator = EVALUATORS[track.evaluator_key]
    try:
        new_value = evaluator(ctx)
    except Exception as e:
        logger.warning("wa_achievements_eval_failed", track=str(track.key), team_id=ctx.team.id, exc_info=True)
        capture_exception(e)
        return

    _apply_progress(ctx, track, progress.pk, new_value)


def _apply_progress(ctx: EvalContext, track: TrackDefinition, progress_pk: UUID, new_value: int) -> list[int]:
    with transaction.atomic():
        progress = WebAnalyticsAchievementProgress.objects.for_team(ctx.team.id).select_for_update().get(pk=progress_pk)
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


@shared_task(ignore_result=True)
@skip_team_scope_audit
def sweep_web_analytics_achievement_team_tracks() -> None:
    window_start = date.today() - timedelta(days=SWEEP_ACTIVE_WINDOW_DAYS)
    team_ids = (
        WebAnalyticsVisit.objects.unscoped()
        .filter(visit_date__gte=window_start)
        .values_list("team_id", flat=True)
        .distinct()
    )
    for team_id in team_ids:
        try:
            team = Team.objects.get(id=team_id)
            enqueue_recompute_web_analytics_achievements_debounced(team_id, None, team_local_today(team))
        except Exception:
            logger.warning("wa_achievements_sweep_enqueue_failed", team_id=team_id, exc_info=True)
