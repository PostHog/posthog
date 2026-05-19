from __future__ import annotations

from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team

from products.tasks.backend.services.custom_prompt_internals import CustomPromptSandboxContext


def resolve_sandbox_context_for_local_dev(repository: str) -> CustomPromptSandboxContext:
    """
    Build a CustomPromptSandboxContext from the first team/user in the local database.
    Requires a GitHub integration to exist for the team (Task.create_and_run resolves it automatically).
    """
    team = Team.objects.select_related("organization").first()
    if not team:
        raise RuntimeError("No team found in local database")
    membership = OrganizationMembership.objects.filter(organization=team.organization).order_by("id").first()
    if not membership:
        raise RuntimeError(f"No users in organization '{team.organization.name}' (team {team.id})")
    user = membership.user
    # Validate the integration exists upfront so we fail early with a clear message.
    gh = Integration.objects.filter(team=team, kind="github").first()
    if not gh:
        raise RuntimeError(
            f"No GitHub integration found for team {team.id}. "
            "Set up a GitHub App installation first: "
            "go to /settings/integrations in your local PostHog."
        )
    return CustomPromptSandboxContext(
        team_id=team.id,
        user_id=user.id,
        repository=repository,
    )
