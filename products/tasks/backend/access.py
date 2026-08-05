from typing import TYPE_CHECKING

from django.core.cache import cache

import posthoganalytics

from posthog.models.user import User

from .models import CodeInviteRedemption

if TYPE_CHECKING:
    from posthog.models.team.team import Team

# `has_tasks_access` runs on every task-run command, including every follow-up message to a live
# run, so a single transient remote flag-evaluation failure must not deny a user mid-conversation.
# Cache a positive result briefly and trust it over a `None` (unknown/errored) re-check.
_TASKS_ACCESS_CACHE_TTL_SECONDS = 300


def _is_flag_enabled(flag_key: str, user: User, team: "Team | None" = None) -> bool | None:
    """Returns None when the remote evaluation itself failed or timed out, distinct from a real `False`."""
    if not user.distinct_id:
        return False
    org = team.organization if team is not None else getattr(user, "organization", None)
    kwargs: dict = {
        "only_evaluate_locally": False,
        "send_feature_flag_events": False,
    }
    if org is not None:
        # The `tasks` flag's release conditions are mostly person-level (email allowlist + domain),
        # but maybe we want org level conditions later on.
        org_id = str(org.id)
        kwargs["groups"] = {"organization": org_id}
        kwargs["group_properties"] = {"organization": {"id": org_id}}
    result = posthoganalytics.feature_enabled(flag_key, user.distinct_id, **kwargs)
    return result if result is None else bool(result)


def has_tasks_access(user: User) -> bool:
    """
    User has access to PostHog Desktop if the `tasks` feature flag is enabled for them
    OR they have redeemed an invite code.
    """
    if not user or not user.is_authenticated:
        return False
    cache_key = f"tasks_access:{user.id}"
    flag_result = _is_flag_enabled("tasks", user)
    if flag_result is None:
        # Remote evaluation errored or timed out, so don't let that collapse into a denial for a
        # user who was granted access moments ago; fall through to the invite-code check otherwise.
        if cache.get(cache_key):
            return True
    elif flag_result:
        cache.set(cache_key, True, _TASKS_ACCESS_CACHE_TTL_SECONDS)
        return True
    return CodeInviteRedemption.objects.filter(user=user).exists()


def has_loops_access(user: User, team: "Team | None" = None) -> bool:
    """Loops sits behind its own flag layered on tasks access (see docs/LOOPS.md Rollout)."""
    if not has_tasks_access(user):
        return False
    return bool(_is_flag_enabled("loops", user, team))
