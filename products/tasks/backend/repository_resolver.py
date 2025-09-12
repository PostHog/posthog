"""
Repository resolution helpers for the multi-repository issue tracker system.
"""

import fnmatch
from typing import Any, Optional

from django.apps import apps

from posthog.models.integration import GitHubIntegration, Integration


class RepositoryContext:
    """Context object for a resolved repository"""

    def __init__(self, integration: Integration, repository: str, organization: str, is_primary: bool = False):
        self.integration = integration
        self.repository = repository
        self.organization = organization
        self.is_primary = is_primary
        self.github_integration = GitHubIntegration(integration)

    @property
    def full_name(self) -> str:
        return f"{self.organization}/{self.repository}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "org": self.organization,
            "repo": self.repository,
            "integration_id": self.integration.id,
            "full_name": self.full_name,
            "is_primary": self.is_primary,
        }


async def resolve_repositories_for_issue(issue) -> list[RepositoryContext]:
    """
    Resolves the actual repositories the agent can work with for an issue.

    Args:
        issue: Issue model instance

    Returns:
        List of RepositoryContext objects
    """
    Task = apps.get_model("tasks", "Task")

    if issue.repository_scope == Task.RepositoryScope.SINGLE:
        return await resolve_single_repository(issue)

    elif issue.repository_scope == Task.RepositoryScope.MULTIPLE:
        return await resolve_multiple_repositories(issue)

    elif issue.repository_scope == Task.RepositoryScope.SMART_SELECT:
        return await resolve_smart_select_repositories(issue)

    # Fallback to legacy behavior
    return await resolve_legacy_repository(issue)


async def resolve_single_repository(issue) -> list[RepositoryContext]:
    """Resolve a single repository for the issue"""
    config = issue.repository_config
    integration = issue.github_integration

    if not integration:
        # Fallback to team's first GitHub integration
        integration = await _get_team_github_integration(issue.team_id)
        if not integration:
            return []

    org = config.get("organization")
    repo = config.get("repository")

    if not org or not repo:
        # If not configured, use the first available repository
        github = GitHubIntegration(integration)
        repositories = github.list_repositories()
        if repositories:
            org = github.organization()
            repo = repositories[0]
        else:
            return []

    return [RepositoryContext(integration=integration, repository=repo, organization=org, is_primary=True)]


async def resolve_multiple_repositories(issue) -> list[RepositoryContext]:
    """Resolve multiple repositories for the issue"""
    repositories_config = issue.repository_config.get("repositories", [])
    resolved_repos = []

    for repo_config in repositories_config:
        integration_id = repo_config.get("integration_id")
        org = repo_config.get("org")
        repo = repo_config.get("repo")
        is_primary = repo_config.get("is_primary", False)

        if not integration_id or not org or not repo:
            continue

        try:
            integration = await Integration.objects.aget(id=integration_id, kind="github")
            resolved_repos.append(
                RepositoryContext(integration=integration, repository=repo, organization=org, is_primary=is_primary)
            )
        except Integration.DoesNotExist:
            continue

    return resolved_repos


async def resolve_smart_select_repositories(issue) -> list[RepositoryContext]:
    """
    AI-driven repository selection with constraints.
    This will be called when the agent needs to dynamically select repositories.
    """
    constraints = issue.repository_config.get("constraints", {})

    # Get all available repositories from allowed integrations
    available_repos = []
    allowed_integrations = await _get_allowed_integrations_for_smart_select(issue, constraints)

    for integration in allowed_integrations:
        github = GitHubIntegration(integration)
        try:
            repos = github.list_repositories()
            org = github.organization()

            for repo in repos:
                if await _meets_smart_select_constraints(org, repo, constraints):
                    available_repos.append(
                        RepositoryContext(integration=integration, repository=repo, organization=org)
                    )
        except Exception:
            continue

    # For now, return available repositories
    # In future iterations, this will include AI analysis
    max_repos = int(constraints.get("max_repositories", 5))
    selected_repos = available_repos[:max_repos]

    # Mark first as primary
    if selected_repos:
        selected_repos[0].is_primary = True

    # Update issue config with selected repositories
    await _update_issue_selected_repositories(issue, selected_repos)

    return selected_repos


async def resolve_legacy_repository(issue) -> list[RepositoryContext]:
    """Fallback to legacy single repository behavior"""
    integration = issue.legacy_github_integration
    if not integration:
        return []

    github = GitHubIntegration(integration)
    repositories = github.list_repositories()

    if not repositories:
        return []

    return [
        RepositoryContext(
            integration=integration, repository=repositories[0], organization=github.organization(), is_primary=True
        )
    ]


async def validate_repository_access(issue, org: str, repo: str) -> bool:
    """
    Validate that an issue can access a specific repository based on its scoping configuration.

    Args:
        issue: Issue model instance
        org: Organization name
        repo: Repository name

    Returns:
        True if access is allowed, False otherwise
    """
    return issue.can_access_repository(org, repo)


async def get_primary_repository(issue) -> Optional[RepositoryContext]:
    """Get the primary repository for an issue"""
    repositories = await resolve_repositories_for_issue(issue)

    # Look for explicitly marked primary repository
    for repo in repositories:
        if repo.is_primary:
            return repo

    # Default to first repository
    return repositories[0] if repositories else None


async def _get_team_github_integration(team_id: int) -> Optional[Integration]:
    """Get the team's first GitHub integration"""
    try:
        return await Integration.objects.filter(team_id=team_id, kind="github").afirst()
    except Integration.DoesNotExist:
        return None


async def _get_allowed_integrations_for_smart_select(issue, constraints: dict) -> list[Integration]:
    """Get allowed integrations based on smart select constraints"""
    allowed_orgs = constraints.get("organizations", [])

    integrations = []
    async for integration in Integration.objects.filter(team_id=issue.team_id, kind="github"):
        github = GitHubIntegration(integration)
        org = github.organization()

        # If organizations are specified, only include matching ones
        if allowed_orgs and org not in allowed_orgs:
            continue

        integrations.append(integration)

    return integrations


async def _meets_smart_select_constraints(org: str, repo: str, constraints: dict) -> bool:
    """Check if a repository meets smart select constraints"""
    allowed_repos = constraints.get("repositories", [])

    if allowed_repos:
        repo_full_name = f"{org}/{repo}"
        # Support wildcard patterns like "PostHog/*" or "*-api"
        if not any(fnmatch.fnmatch(repo_full_name, pattern) for pattern in allowed_repos):
            return False

    return True


async def _update_issue_selected_repositories(issue, selected_repos: list[RepositoryContext]) -> None:
    """Update issue configuration with selected repositories"""
    Task = apps.get_model("tasks", "Task")

    available_repositories = [repo.to_dict() for repo in selected_repos]

    # Update the issue's repository config
    issue.repository_config = {**issue.repository_config, "available_repositories": available_repositories}

    await Task.objects.filter(id=issue.id).aupdate(repository_config=issue.repository_config)


# Smart selection AI helpers (placeholder for future implementation)
async def ai_select_repositories(
    issue, available_repositories: list[RepositoryContext], max_count: int, preferences: dict
) -> list[RepositoryContext]:
    """
    Use AI to analyze issue and select most relevant repositories.
    This is a placeholder for future AI implementation.
    """
    # For now, use simple heuristics
    selected = []

    # Prefer repositories with keywords matching the issue
    issue_keywords = issue.title.lower().split() + issue.description.lower().split()

    for repo in available_repositories:
        score: float = 0.0
        repo_name = repo.repository.lower()

        # Score based on keyword matches
        for keyword in issue_keywords:
            if keyword in repo_name:
                score += 1

        # Prefer recently active repositories (placeholder)
        if preferences.get("prefer_recent_activity", False):
            score += 0.5

        selected.append((repo, score))

    # Sort by score and take top repositories
    selected.sort(key=lambda x: x[1], reverse=True)
    return [repo for repo, _ in selected[:max_count]]
