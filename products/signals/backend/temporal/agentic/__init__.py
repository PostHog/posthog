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


def get_or_create_signals_sandbox_env(
    team_id: int,
    name: str,
    network_access_level: "tasks_facade.SandboxNetworkAccessLevel",
    *,
    allowed_domains: list[str] | None = None,
    include_default_domains: bool = False,
) -> str:
    """Get or create a SandboxEnvironment for a Signals agent. Returns the env ID as a string.

    Reasserts the expected policy on every call, so manual edits via the API are corrected on
    next run.
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

    Pass `github` if the caller already resolved it to skip a duplicate query.
    """
    team = Team.objects.select_related("organization").get(id=team_id)
    if github is None:
        github = resolve_team_github_integration(team_id, team=team)
    if github is None:
        raise RuntimeError(f"No GitHub integration for team {team_id}; caller must short-circuit before calling this")
    # Pick the user who created the integration
    if isinstance(github, UserGitHubIntegration):
        return github.integration.user_id
    # If team-level Integration, prefer its creator (if still active in the org)
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
    # Integration exists but its creator is gone — pick any active org member as a stand-in.
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
    """Resolve the user a Signals scout sandbox acts as, *without* requiring GitHub.

    `resolve_user_id_for_team` gates on a GitHub integration because the repo-cloning callers
    (report generation, repo selection, custom agent) need those credentials. The scout cadence
    path never clones a repo — `user_id` only scopes the sandbox connection token / MCP identity —
    so a GitHub integration is the wrong precondition there. Prefer the GitHub-integration creator
    when one exists (stable attribution, matches the other surfaces), otherwise fall back to any
    active org member.

    Returns ``None`` only when the org has no active member to act as — a genuine "can't run yet"
    that the scheduled caller short-circuits on, rather than crashing deep in the spawn path and
    booking a bogus `failed` outcome. Genuine errors (missing team, DB failures) still propagate.
    """
    team = Team.objects.select_related("organization").get(id=team_id)
    github = resolve_team_github_integration(team_id, team=team)
    if github is not None:
        try:
            return resolve_user_id_for_team(team_id, github=github)
        except RuntimeError:
            # Integration present but its user is unusable — fall through to any active member.
            pass
    membership = (
        OrganizationMembership.objects.select_related("user")
        .filter(organization=team.organization, user__is_active=True)
        .order_by("id")
        .first()
    )
    return membership.user_id if membership else None
