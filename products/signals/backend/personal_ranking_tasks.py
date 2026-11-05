from django.core.cache import cache
from django.utils import timezone

from celery import shared_task

from posthog.models import Team, User
from posthog.models.scoping import with_team_scope

from products.signals.backend.personal_ranking.build_budget import spend_shared_build
from products.signals.backend.personal_ranking.config import PersonalRankingConfig, read_config
from products.signals.backend.personal_ranking.logic import build_personal_ranking, check_inputs

# Above the task's time_limit, so a live build never loses its lock. It also frees the lock of a worker that died.
BUILD_LOCK_TTL_SECONDS = 5 * 60


def build_lock_key(team_id: int, user_id: int) -> str:
    return f"signals_personal_ranking_build/{team_id}/{user_id}"


def _skip_build(team: Team, user: User, config: PersonalRankingConfig) -> bool:
    """Compare the latest list with the current inputs, as the tick does. True when the build must not run."""
    check = check_inputs(team, user, config, now=timezone.now())
    if check.unchanged:
        return True
    # The read did not gather the candidates, so it could not know whether the build calls the model.
    return check.calls_model and spend_shared_build(config) is not None


@shared_task(ignore_result=True, max_retries=0, soft_time_limit=3 * 60, time_limit=4 * 60)
@with_team_scope()
def build_personal_inbox_ranking(
    team_id: int, user_id: int, focus: str | None, limit: int | None, check_first: bool = False
) -> None:
    """Build and store one person's ranked inbox list. The `for_me` read takes the lock before it queues this task.

    With `check_first`, a list that still matches the current inputs gets `checked_at` and no model call, and a
    build that calls the model spends the shared daily limit first.
    """
    try:
        team = Team.objects.select_related("organization").filter(id=team_id).first()
        user = User.objects.filter(id=user_id).first()
        if team is None or user is None:
            return
        config = read_config()
        if check_first and _skip_build(team, user, config):
            return
        build_personal_ranking(team, user, focus=focus, limit=limit, config=config)
    finally:
        cache.delete(build_lock_key(team_id, user_id))
