import logging

from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team

logger = logging.getLogger(__name__)


def resolve_default_run_user_id(team_id: int) -> int | None:
    """The user ReviewHog acts as when no better identity applies: the GitHub integration creator if
    still an active org member, else the oldest active org member (same semantics as signals'
    resolve_user_id_for_team). Shared by the trigger's sandbox run-user resolution and the label
    trigger's last acting-user fallback.

    A disabled user is worse than none: every user-scoped sandbox credential 403s and the agent
    hangs silently until the poll budget expires, so never return an inactive user here.
    """
    team = Team.objects.select_related("organization").get(id=team_id)
    integration = Integration.objects.filter(team_id=team_id, kind="github").order_by("id").first()
    if integration is not None and integration.created_by_id:
        creator_is_active = OrganizationMembership.objects.filter(
            organization=team.organization,
            user_id=integration.created_by_id,
            user__is_active=True,
        ).exists()
        if creator_is_active:
            return integration.created_by_id
        logger.warning(
            "ReviewHog default-user fallback: integration creator %s is not an active org member",
            integration.created_by_id,
        )
    membership = (
        OrganizationMembership.objects.select_related("user")
        .filter(organization=team.organization, user__is_active=True)
        .order_by("id")
        .first()
    )
    return membership.user_id if membership else None
