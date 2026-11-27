from django.db import transaction
from django.utils import timezone

import structlog

from posthog.models import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.web_analytics.backend.achievements.definitions import TRACKS, TrackDefinition
from products.web_analytics.backend.achievements.evaluators import EVALUATORS, EvalContext
from products.web_analytics.backend.achievements.tasks import get_or_create_progress, persist_progress, team_local_today
from products.web_analytics.backend.models import WebAnalyticsAchievementProgress

logger = structlog.get_logger(__name__)


def backfill_team(team_id: int) -> int:
    """Seed cumulative-track progress for a team's members from historical data, without
    queuing any celebrations. Returns the number of progress rows touched."""
    team = Team.objects.get(id=team_id)
    today = team_local_today(team)
    member_user_ids = OrganizationMembership.objects.filter(organization_id=team.organization_id).values_list(
        "user_id", flat=True
    )
    cumulative_tracks = [track for track in TRACKS.values() if track.is_cumulative]
    return sum(
        _backfill_track(EvalContext(team=team, user=user, today=today, arm=None), track)
        for user in User.objects.filter(id__in=member_user_ids)
        for track in cumulative_tracks
    )


def _backfill_track(ctx: EvalContext, track: TrackDefinition) -> bool:
    progress = get_or_create_progress(ctx, track)
    try:
        evaluated_value = EVALUATORS[track.evaluator_key](ctx)
    except Exception:
        logger.warning("wa_achievements_backfill_failed", track=str(track.key), team_id=ctx.team.id, exc_info=True)
        return False
    with transaction.atomic():
        current = WebAnalyticsAchievementProgress.objects.for_team(ctx.team.id).select_for_update().get(pk=progress.pk)
        value = max(evaluated_value, current.progress_value)
        stage = track.stage_for_value(value, None)
        seeded_at = timezone.now().isoformat()
        state = dict(current.state or {})
        unlocked_stages = dict(state.get("unlocked_stages", {}))
        for unlocked_stage in range(1, stage + 1):
            unlocked_stages.setdefault(str(unlocked_stage), seeded_at)
        state["unlocked_stages"] = unlocked_stages
        state.setdefault("pending_celebrations", [])
        persist_progress(current, value, max(current.current_stage, stage), state)
    return True
