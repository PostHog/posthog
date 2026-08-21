import structlog

from posthog.models.github_integration_base import GitHubIntegrationBase
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user_integration import UserGitHubIntegration

from products.signals.backend.report_generation.select_repo import resolve_team_github_integration
from products.tasks.backend.facade import api as tasks_facade

logger = structlog.get_logger(__name__)

SIGNALS_REPO_DISCOVERY_ENV_NAME = "SIGNALS_REPO_DISCOVERY"
SIGNALS_REPORT_RESEARCH_ENV_NAME = "SIGNALS_REPORT_RESEARCH"
SIGNALS_REPORT_CANVAS_ENV_NAME = "SIGNALS_REPORT_CANVAS"


def get_or_create_signals_sandbox_env(
    team_id: int,
    name: str,
    network_access_level: "tasks_facade.SandboxNetworkAccessLevel",
    *,
    allowed_domains: list[str] | None = None,
    include_default_domains: bool = False,
) -> str:
    """Get or create a SandboxEnvironment for a Signals agent. Returns its ID as a string.

    Reasserts the expected policy on every call, so manual edits via the API are corrected on
    the next run.
    """
    return str(
        tasks_facade.upsert_internal_sandbox_env(
            team_id,
            name,
            network_access_level,
            allowed_domains=allowed_domains,
            include_default_domains=include_default_domains,
        )
    )


def resolve_user_id_for_team(team_id: int, github: GitHubIntegrationBase | None = None) -> int:
    """Resolve the best user ID for automated sandbox actions on behalf of a team.

    Pass ``github`` if the caller already resolved it to skip a duplicate query.
    """
    team = Team.objects.select_related("organization").get(id=team_id)
    if github is None:
        github = resolve_team_github_integration(team_id, team=team)
    if github is None:
        raise RuntimeError(f"No GitHub integration for team {team_id}; caller must short-circuit before calling this")
    # Prefer the user who created the integration so automated work has stable attribution.
    if isinstance(github, UserGitHubIntegration):
        return github.integration.user_id
    if github.integration.created_by_id:
        is_active = OrganizationMembership.objects.filter(
            organization=team.organization,
            user_id=github.integration.created_by_id,
            user__is_active=True,
        ).exists()
        if is_active:
            return github.integration.created_by_id
        logger.warning(
            "github integration creator is no longer an active org member, falling back",
            team_id=team_id,
            integration_created_by=github.integration.created_by_id,
        )
    membership = (
        OrganizationMembership.objects.select_related("user")
        .filter(organization=team.organization, user__is_active=True)
        .order_by("id")
        .first()
    )
    if not membership:
        raise RuntimeError(f"No active users in organization '{team.organization.name}' (team {team.id})")
    return membership.user_id


def resolve_acting_user_id_for_team(team_id: int) -> int | None:
    """Resolve a Signals sandbox user without requiring a GitHub integration.

    Repo-less agents only need a user to scope the sandbox token, so a missing GitHub
    integration should not prevent them from running. Returns ``None`` only when the
    organization has no active member.
    """
    team = Team.objects.select_related("organization").get(id=team_id)
    github = resolve_team_github_integration(team_id, team=team)
    if github is not None:
        try:
            return resolve_user_id_for_team(team_id, github=github)
        except RuntimeError:
            pass
    membership = (
        OrganizationMembership.objects.select_related("user")
        .filter(organization=team.organization, user__is_active=True)
        .order_by("id")
        .first()
    )
    return membership.user_id if membership else None
