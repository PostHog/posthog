from django.utils import timezone

import structlog

from posthog.models import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.web_analytics.backend.achievements.definitions import TRACKS, AchievementScope, TrackDefinition
from products.web_analytics.backend.achievements.evaluators import EVALUATORS, EvalContext
from products.web_analytics.backend.achievements.tasks import get_or_create_progress, persist_progress, team_local_today

logger = structlog.get_logger(__name__)

BACKFILLABLE_EVALUATOR_KEYS = {
    "loyal_days",
    "cumulative_pageviews",
    "conversions",
    "data_events",
    "recordings_opened",
}


def backfill_team(team_id: int) -> int:
    """Seed cumulative-track progress for a team and its members from historical data, without
    queuing any celebrations. Returns the number of progress rows touched."""
    team = Team.objects.get(id=team_id)
    today = team_local_today(team)
    touched = _backfill_scope(EvalContext(team=team, user=None, today=today, arm=None))
    member_user_ids = OrganizationMembership.objects.filter(organization_id=team.organization_id).values_list(
        "user_id", flat=True
    )
    for user in User.objects.filter(id__in=member_user_ids):
        touched += _backfill_scope(EvalContext(team=team, user=user, today=today, arm=None))
    return touched


def _backfill_scope(ctx: EvalContext) -> int:
    touched = 0
    for track in TRACKS.values():
        if track.evaluator_key not in BACKFILLABLE_EVALUATOR_KEYS:
            continue
        if track.scope == AchievementScope.USER and ctx.user is None:
            continue
        if track.scope == AchievementScope.TEAM and ctx.user is not None:
            continue
        if _backfill_track(ctx, track):
            touched += 1
    return touched


def _backfill_track(ctx: EvalContext, track: TrackDefinition) -> bool:
    progress = get_or_create_progress(ctx, track)
    evaluator = EVALUATORS[track.evaluator_key]
    try:
        value = max(evaluator(ctx), progress.progress_value)
    except Exception:
        logger.warning("wa_achievements_backfill_failed", track=str(track.key), team_id=ctx.team.id, exc_info=True)
        return False
    stage = track.stage_for_value(value, None)
    seeded_at = timezone.now().isoformat()
    state = dict(progress.state or {})
    unlocked_stages = dict(state.get("unlocked_stages", {}))
    for unlocked_stage in range(1, stage + 1):
        unlocked_stages.setdefault(str(unlocked_stage), seeded_at)
    state["unlocked_stages"] = unlocked_stages
    state.setdefault("pending_celebrations", [])
    # Leave last_computed_at untouched so the next live recompute still runs the same day a team is
    # backfilled — backfilling must not suppress real-time unlocks.
    persist_progress(progress, value, max(progress.current_stage, stage), state, bump_last_computed_at=False)
    return True
