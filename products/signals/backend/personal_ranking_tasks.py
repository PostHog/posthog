from django.core.cache import cache
from django.utils import timezone

from celery import shared_task

from posthog.models import Team, User
from posthog.models.scoping import with_team_scope

from products.signals.backend.models import PersonalInboxRanking
from products.signals.backend.personal_ranking.build_budget import spend_shared_build
from products.signals.backend.personal_ranking.config import PersonalRankingConfig, read_config
from products.signals.backend.personal_ranking.logic import BuildTrigger, build_personal_ranking, check_inputs

# Above the task's time_limit, so a live build never loses its lock. It also frees the lock of a worker that died.
BUILD_LOCK_TTL_SECONDS = 5 * 60


def build_lock_key(team_id: int, user_id: int) -> str:
    return f"signals_personal_ranking_build/{team_id}/{user_id}"


def _skip_build(
    team: Team, user: User, config: PersonalRankingConfig, limit: int | None, *, model_only: bool = False
) -> bool:
    """Compare the latest list with the current inputs, as the tick does. True when the build must not run.

    With `model_only`, a build that would not call the model does not run either.
    """
    check = check_inputs(team, user, config, now=timezone.now(), limit=limit)
    if check.unchanged:
        return True
    if not check.calls_model:
        return model_only
    # The read did not gather the candidates, so it could not know whether the build calls the model.
    return spend_shared_build(config) is not None


@shared_task(ignore_result=True, max_retries=0, soft_time_limit=3 * 60, time_limit=4 * 60)
@with_team_scope()
def build_personal_inbox_ranking(
    team_id: int,
    user_id: int,
    focus: str | None,
    limit: int | None,
    check_first: bool = False,
    trigger: BuildTrigger = "on_demand",
) -> None:
    """Build and store one person's ranked inbox list. The caller takes the lock before it queues this task.

    With `check_first`, a list that still matches the current inputs gets `checked_at` and no model call, and a
    build that calls the model spends the shared daily limit first. A `first_summary` build runs only when it
    calls the model.
    """
    try:
        team = Team.objects.select_related("organization").filter(id=team_id).first()
        user = User.objects.filter(id=user_id).first()
        if team is None or user is None:
            return
        config = read_config()
        if check_first and _skip_build(team, user, config, limit, model_only=trigger == "first_summary"):
            return
        build_personal_ranking(team, user, focus=focus, limit=limit, config=config, trigger=trigger)
    finally:
        cache.delete(build_lock_key(team_id, user_id))


def start_first_summary_build(team_id: int, user_id: int) -> bool:
    """Queue a build for a person whose first activity summary was just stored. True when the build is queued.

    The person has no list until a build stores one, so without this build the first list waits for the
    personal ranking tick. A pair that already has a list, or that this function does not queue, stays with the tick.
    """
    if not read_config().enabled:
        return False
    if PersonalInboxRanking.objects.for_team(team_id).filter(user_id=user_id).exists():
        return False
    lock_key = build_lock_key(team_id, user_id)
    if not cache.add(lock_key, "1", timeout=BUILD_LOCK_TTL_SECONDS):
        return False
    try:
        build_personal_inbox_ranking.delay(team_id, user_id, None, None, True, "first_summary")
    except Exception:
        cache.delete(lock_key)
        raise
    return True
