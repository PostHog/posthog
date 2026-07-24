from typing import TYPE_CHECKING

import posthoganalytics

from posthog.models.user import User

from .models import CodeInviteRedemption

if TYPE_CHECKING:
    from posthog.models.team.team import Team


def _is_flag_enabled(flag_key: str, user: User, team: "Team | None" = None) -> bool:
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
    return bool(posthoganalytics.feature_enabled(flag_key, user.distinct_id, **kwargs))


def has_tasks_access(user: User) -> bool:
    """
    User has access to PostHog Code if the `tasks` feature flag is enabled for them
    OR they have redeemed an invite code.
    """
    if not user or not user.is_authenticated:
        return False
    if _is_flag_enabled("tasks", user):
        return True
    return CodeInviteRedemption.objects.filter(user=user).exists()


def has_loops_access(user: User, team: "Team | None" = None) -> bool:
    """Loops sits behind its own flag layered on tasks access (see docs/LOOPS.md Rollout)."""
    if not has_tasks_access(user):
        return False
    return _is_flag_enabled("loops", user, team)
