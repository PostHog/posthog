import structlog

from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team

logger = structlog.get_logger(__name__)


def resolve_user_id_for_team(team_id: int) -> int:
    """Resolve the best user ID for automated sandbox actions on behalf of a team."""
    team = Team.objects.select_related("organization").get(id=team_id)
    github_integration = Integration.objects.filter(team=team, kind="github").first()
    # Prefer the user who set up the GitHub integration
    if github_integration and github_integration.created_by_id:
        is_active = OrganizationMembership.objects.filter(
            organization=team.organization,
            user_id=github_integration.created_by_id,
            user__is_active=True,
        ).exists()
        if is_active:
            return github_integration.created_by_id
        logger.warning(
            "github integration creator is no longer an active org member, falling back to first active member",
            team_id=team_id,
            integration_created_by=github_integration.created_by_id,
        )
    # Fallback: first active org member
    membership = (
        OrganizationMembership.objects.select_related("user")
        .filter(organization=team.organization, user__is_active=True)
        .order_by("id")
        .first()
    )
    if not membership:
        raise RuntimeError(f"No active users in organization '{team.organization.name}' (team {team.id})")
    return membership.user_id
