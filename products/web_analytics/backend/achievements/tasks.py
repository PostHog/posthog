import random
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
)
from products.web_analytics.backend.achievements.evaluators import (
    EVALUATORS,
    EvalContext,
    count_cumulative_pageviews_since,
)
from products.web_analytics.backend.models import (
    WebAnalyticsAchievementProgress,
    WebAnalyticsUserConfig,
    WebAnalyticsVisit,
)

logger = structlog.get_logger(__name__)

RECOMPUTE_DEBOUNCE_TTL_SECONDS = 26 * 60 * 60
STREAK_CADENCE_FLAG = "web-analytics-streak-cadence"
ACHIEVEMENTS_FLAG = "web-analytics-achievements"
SWEEP_ACTIVE_WINDOW_DAYS = 7
# The daily gate means every active team comes due at once, so the sweep would otherwise fire all
# recomputes in one burst and their ClickHouse queries exhaust the shared query pool. Spread each
# team's recompute over a random offset within this window to flatten the fan-out. Well under the
# 6-hourly sweep cadence, so a team is still recomputed the same day.
SWEEP_STAGGER_SECONDS = 30 * 60

# Where the Traffic track keeps its running pageview total and the cursor (ISO-8601) marking the
# window end already counted, so each recompute only counts the bounded delta since the last run.
PAGEVIEWS_STATE_KEY = "pageviews"

# Only these (ClickHouse-backed) evaluators are gated to once per team-local day. The cheap DB-backed
# tracks (streak, loyalty, first-party interaction counters) recompute on every trigger so they stay
# same-day fresh.
EXPENSIVE_EVALUATOR_KEYS = {"cumulative_pageviews", "conversions"}


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


def enqueue_recompute_web_analytics_achievements_debounced(
    team_id: int, user_id: int | None, today: date, countdown: int = 0
) -> bool:
    """Enqueue a recompute for this scope at most once per team-local day. Date-keyed (not a rolling
    24h TTL) so the first visit each day recomputes promptly, keeping streaks fresh. Fails open on a
    cache error so a Redis blip can't drop the visit signal. `countdown` staggers the periodic sweep;
    real-time visit signals leave it at 0 so they recompute promptly."""
    scope = str(user_id) if user_id is not None else "team"
    debounce_key = f"wa_achievements_recompute:{team_id}:{scope}:{today.isoformat()}"
    try:
        was_added = cache.add(debounce_key, "1", timeout=RECOMPUTE_DEBOUNCE_TTL_SECONDS)
    except Exception as e:
        logger.warning("wa_achievements_debounce_cache_failure", team_id=team_id, exc_info=True)
        capture_exception(e)
        was_added = True
    if was_added:
        recompute_web_analytics_achievements.apply_async(
            args=[team_id], kwargs={"user_id": user_id}, countdown=countdown or None
        )
        return True
    return False


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
        if cheap_only and track.evaluator_key in EXPENSIVE_EVALUATOR_KEYS:
            continue
        _recompute_track(ctx, track)


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


def _recompute_track(ctx: EvalContext, track: TrackDefinition) -> None:
    progress = get_or_create_progress(ctx, track)
    if progress.current_stage >= len(track.stages):
        return
    if track.evaluator_key in EXPENSIVE_EVALUATOR_KEYS and not is_due(ctx, progress):
        return
    if track.evaluator_key == "cumulative_pageviews":
        _recompute_cumulative_pageviews(ctx, track, progress)
        return
    evaluator = EVALUATORS[track.evaluator_key]
    try:
        new_value = evaluator(ctx)
    except Exception as e:
        logger.warning("wa_achievements_eval_failed", track=str(track.key), team_id=ctx.team.id, exc_info=True)
        capture_exception(e)
        return

    _apply_progress(ctx, track, progress.pk, new_value)


def _recompute_cumulative_pageviews(
    ctx: EvalContext, track: TrackDefinition, progress: WebAnalyticsAchievementProgress
) -> None:
    """Accumulate the bounded pageview delta since the last recompute onto the team's running total,
    instead of re-counting all of history every time. The first recompute for a team simply plants
    the cursor at `now` (historical totals come from the manual backfill seed) — so the periodic
    sweep never runs an unbounded full-table scan."""
    prev = (progress.state or {}).get(PAGEVIEWS_STATE_KEY) or {}
    # Fall back to progress_value so a team seeded by backfill (which sets progress_value but not
    # this cursor state) keeps accumulating on top of its historical total rather than from zero.
    prev_total = max(int(prev.get("total") or 0), progress.progress_value)
    prev_through = _parse_iso(prev.get("counted_through"))
    until = timezone.now()
    try:
        delta = count_cumulative_pageviews_since(ctx, prev_through, until) if prev_through is not None else 0
    except Exception as e:
        logger.warning("wa_achievements_eval_failed", track=str(track.key), team_id=ctx.team.id, exc_info=True)
        capture_exception(e)
        return

    new_total = prev_total + delta
    state_patch = {PAGEVIEWS_STATE_KEY: {"total": new_total, "counted_through": until.isoformat()}}
    _apply_progress(ctx, track, progress.pk, new_total, state_patch)


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _apply_progress(
    ctx: EvalContext, track: TrackDefinition, progress_pk: UUID, new_value: int, state_patch: dict | None = None
) -> list[int]:
    with transaction.atomic():
        progress = WebAnalyticsAchievementProgress.objects.for_team(ctx.team.id).select_for_update().get(pk=progress_pk)
        is_cumulative = track.evaluator_key != "streak"
        value = max(new_value, progress.progress_value) if is_cumulative else new_value
        arm = ctx.arm if track.is_experiment_track else None
        new_stage = max(progress.current_stage, track.stage_for_value(value, arm))

        state = dict(progress.state or {})
        if state_patch:
            state.update(state_patch)
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
                priority=Priority.NORMAL,
                source_url=f"/project/{ctx.team.id}/web",
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
            countdown = random.randint(0, SWEEP_STAGGER_SECONDS)
            enqueue_recompute_web_analytics_achievements_debounced(
                team_id, None, team_local_today(team), countdown=countdown
            )
        except Exception:
            logger.warning("wa_achievements_sweep_enqueue_failed", team_id=team_id, exc_info=True)
