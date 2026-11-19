from datetime import date, datetime
from functools import partial

from django.db import transaction
from django.utils import timezone

import structlog
import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.models.user import User

from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    TargetType,
    create_notification,
)
from products.web_analytics.backend.achievements.definitions import STREAK_ARM_CONTROL, TRACKS, TrackDefinition
from products.web_analytics.backend.achievements.evaluators import EVALUATORS, EvalContext
from products.web_analytics.backend.models import (
    WebAnalyticsAchievementProgress,
    WebAnalyticsUserConfig,
    WebAnalyticsVisit,
)

logger = structlog.get_logger(__name__)

STREAK_CADENCE_FLAG = "web-analytics-streak-cadence"
ACHIEVEMENTS_FLAG = "web-analytics-achievements"


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


def recompute_web_analytics_achievements(team: Team, user: User) -> None:
    arm = streak_arm_for_user(user)
    if arm == STREAK_ARM_CONTROL:
        return
    ctx = EvalContext(team=team, user=user, today=team_local_today(team), arm=arm)
    for track in TRACKS.values():
        _recompute_track(ctx, track)


def get_or_create_progress(ctx: EvalContext, track: TrackDefinition) -> WebAnalyticsAchievementProgress:
    canonical_team_id = ctx.team.parent_team_id or ctx.team.id
    progress, _ = WebAnalyticsAchievementProgress.objects.for_team(canonical_team_id, canonical=True).get_or_create(
        team_id=canonical_team_id,
        user_id=ctx.user.id,
        track_key=str(track.key),
        defaults={"current_stage": 0, "progress_value": 0, "state": {}},
    )
    return progress


def persist_progress(progress: WebAnalyticsAchievementProgress, value: int, stage: int, state: dict) -> None:
    progress.progress_value = value
    progress.current_stage = stage
    progress.last_computed_at = timezone.now()
    progress.state = state
    progress.save()


def _last_visit_date_iso(ctx: EvalContext) -> str | None:
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
    try:
        value = EVALUATORS[track.evaluator_key](ctx)
    except Exception as e:
        logger.warning("wa_achievements_eval_failed", track=str(track.key), team_id=ctx.team.id, exc_info=True)
        capture_exception(e)
        return

    _apply_progress(ctx, track, progress, value)


def _apply_progress(
    ctx: EvalContext,
    track: TrackDefinition,
    evaluated_progress: WebAnalyticsAchievementProgress,
    new_value: int,
) -> None:
    with transaction.atomic():
        progress = (
            WebAnalyticsAchievementProgress.objects.for_team(ctx.team.id)
            .select_for_update(skip_locked=True)
            .filter(pk=evaluated_progress.pk)
            .first()
        )
        if progress is None:
            return
        value = max(new_value, progress.progress_value) if track.is_cumulative else new_value
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


def _send_unlock_notifications(ctx: EvalContext, track: TrackDefinition, stages: list[int]) -> None:
    if _user_opted_out(ctx.team, ctx.user) or not _achievements_flag_enabled(
        str(ctx.user.distinct_id), str(ctx.team.organization_id)
    ):
        return
    for stage in stages:
        _send_unlock_notification(ctx, track, stage)


def _send_unlock_notification(ctx: EvalContext, track: TrackDefinition, stage: int) -> None:
    stage_name = track.stages[stage - 1].name
    try:
        create_notification(
            NotificationData(
                team_id=ctx.team.id,
                notification_type=NotificationType.ACHIEVEMENT_UNLOCKED,
                title=f"Achievement unlocked: {stage_name}",
                body=f"You reached {stage_name} on the {track.display_name} track in Web analytics.",
                target_type=TargetType.USER,
                target_id=str(ctx.user.id),
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
