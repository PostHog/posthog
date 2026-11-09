from django.core.cache import cache

from celery import shared_task

from posthog.models import Team, User
from posthog.models.scoping import with_team_scope

from products.signals.backend.personal_ranking.logic import build_personal_ranking

# Above the task's time_limit, so a live build never loses its lock. It also frees the lock of a worker that died.
BUILD_LOCK_TTL_SECONDS = 5 * 60


def build_lock_key(team_id: int, user_id: int) -> str:
    return f"signals_personal_ranking_build/{team_id}/{user_id}"


@shared_task(ignore_result=True, max_retries=0, soft_time_limit=3 * 60, time_limit=4 * 60)
@with_team_scope()
def build_personal_inbox_ranking(team_id: int, user_id: int, focus: str | None, limit: int | None) -> None:
    """Build and store one person's ranked inbox list. The `for_me` read takes the lock before it queues this task."""
    try:
        team = Team.objects.filter(id=team_id).first()
        user = User.objects.filter(id=user_id).first()
        if team is None or user is None:
            return
        build_personal_ranking(team, user, focus=focus, limit=limit)
    finally:
        cache.delete(build_lock_key(team_id, user_id))
