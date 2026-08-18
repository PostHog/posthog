from typing import TYPE_CHECKING

from django.db.models import Q
from django.utils import timezone

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
    User has access to PostHog Desktop if the `tasks` feature flag is enabled for them
    or they redeemed an active invite code that has not expired.
    """
    if not user or not user.is_authenticated:
        return False
    if _is_flag_enabled("tasks", user):
        return True
    return (
        CodeInviteRedemption.objects.filter(user=user, invite_code__is_active=True)
        .filter(Q(invite_code__expires_at__isnull=True) | Q(invite_code__expires_at__gt=timezone.now()))
        .exists()
    )


def has_loops_access(user: User, team: "Team | None" = None) -> bool:
    """Loops sits behind its own `loops` flag (see docs/LOOPS.md Rollout).

    Independent of `has_tasks_access`: `tasks` gates the Desktop waitlist that user-triggered cloud
    runs require (see code_access_required_response), while Loops gates on its own flag instead.
    """
    return _is_flag_enabled("loops", user, team)
