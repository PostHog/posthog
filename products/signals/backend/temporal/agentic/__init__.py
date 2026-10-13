import structlog

from posthog.models.github_integration_base import GitHubIntegrationBase
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserGitHubIntegration
from posthog.user_permissions import UserPermissions

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


def _can_act_on_team(user_id: int, team: Team) -> bool:
    """Whether a scout run started as this user survives the workflow dispatcher.

    Mirrors `_user_can_dispatch` in the tasks workflow dispatcher, which is the authority. A run
    resolved as a user this returns False for is killed at dispatch and booked as failed.
    """
    user = User.objects.filter(id=user_id, is_active=True).first()
    if user is None:
        return False
    return UserPermissions(user=user, team=team).current_team.effective_membership_level is not None


def resolve_acting_user_id_for_team(team_id: int) -> int | None:
    """Resolve the user a Signals scout sandbox acts as. Does not require a GitHub integration.

    `resolve_user_id_for_team` requires GitHub because its callers clone a repo. The scout cadence
    path does not clone: `user_id` only scopes the sandbox connection token and MCP identity.

    Every candidate must pass `_can_act_on_team`, because the run mints a sandbox token as this
    user. Org membership is not enough. A project can deny a member by going private or by one
    per-member rule, and either way org membership keeps picking a user the dispatcher rejects on
    every tick. `Team.all_users_with_access()` narrows the pool first, which keeps the walk short
    on a private project. Prefer the GitHub integration creator when that user qualifies, so
    attribution matches the other surfaces.

    Return None when the project has no such member. The scheduled caller then skips the tick
    instead of crashing deep in the spawn path and booking a bogus `failed` run. Genuine errors
    (missing team, DB failures) still propagate.
    """
    team = Team.objects.select_related("organization").get(id=team_id)
    github = resolve_team_github_integration(team_id, team=team)
    if github is not None:
        try:
            github_user_id = resolve_user_id_for_team(team_id, github=github)
        except RuntimeError:
            github_user_id = None
        if github_user_id is not None and _can_act_on_team(github_user_id, team):
            return github_user_id
    candidate_ids = (
        OrganizationMembership.objects.filter(organization=team.organization, user__in=team.all_users_with_access())
        .order_by("id")
        .values_list("user_id", flat=True)
    )
    return next((user_id for user_id in candidate_ids.iterator() if _can_act_on_team(user_id, team)), None)
