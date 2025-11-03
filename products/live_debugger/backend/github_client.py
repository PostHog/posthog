"""
GitHub API client for live debugger repository browsing.

Provides access to GitHub repository data using team's GitHub integration.
"""

import base64
from typing import Any

import requests
import structlog
from rest_framework import status

from posthog.models import Team
from posthog.models.integration import GitHubIntegration, Integration

logger = structlog.get_logger(__name__)


class GitHubClientError(Exception):
    """Base exception for GitHub client errors."""

    pass


class GitHubIntegrationNotFoundError(GitHubClientError):
    """Raised when team doesn't have a GitHub integration configured."""

    pass


def get_github_integration(team: Team) -> GitHubIntegration:
    """
    Get the GitHub integration for a team.

    Args:
        team: PostHog team

    Returns:
        GitHubIntegration instance

    Raises:
        GitHubIntegrationNotFoundError: If no GitHub integration exists
    """
    try:
        integration = Integration.objects.get(team=team, kind="github")
        return GitHubIntegration(integration)
    except Integration.DoesNotExist:
        raise GitHubIntegrationNotFoundError(
            "No GitHub integration found. Please set up a GitHub integration for your team."
        )


def list_repositories(team: Team) -> list[dict[str, str]]:
    """
    List all repositories accessible to the team's GitHub integration.

    Args:
        team: PostHog team

    Returns:
        List of repository dicts with 'name' and 'full_name' keys

    Raises:
        GitHubIntegrationNotFoundError: If no GitHub integration exists
        GitHubClientError: If GitHub API request fails
    """
    github_integration = get_github_integration(team)
    org = github_integration.organization()

    repositories = []
    page = 1
    max_pages = 10  # Safety limit

    while page <= max_pages:
        try:
            repo_names = github_integration.list_repositories(page=page)

            if not repo_names:
                break

            for name in repo_names:
                repositories.append({"name": name, "full_name": f"{org}/{name}"})

            page += 1

        except Exception as e:
            logger.exception("Failed to list repositories", team_id=team.pk, page=page)
            raise GitHubClientError(f"Failed to fetch repositories: {str(e)}")

    return repositories


def get_branch_sha(team: Team, repository: str, branch: str) -> str:
    """
    Get the current commit SHA for a branch.

    Args:
        team: PostHog team
        repository: Repository name (just the repo name, not full path)
        branch: Branch name

    Returns:
        Current commit SHA for the branch

    Raises:
        GitHubIntegrationNotFoundError: If no GitHub integration exists
        GitHubClientError: If GitHub API request fails
    """
    github_integration = get_github_integration(team)
    org = github_integration.organization()
    access_token = github_integration.integration.sensitive_config.get("access_token")

    # Refresh token if needed
    try:
        if github_integration.access_token_expired():
            github_integration.refresh_access_token()
            access_token = github_integration.integration.sensitive_config.get("access_token")
    except Exception as e:
        logger.warning("Failed to refresh GitHub token", error=str(e), team_id=team.pk)

    try:
        response = requests.get(
            f"https://api.github.com/repos/{org}/{repository}/branches/{branch}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=10,
        )

        if response.status_code == status.HTTP_404_NOT_FOUND:
            raise GitHubClientError(f"Branch '{branch}' not found in repository '{org}/{repository}'")

        if response.status_code == status.HTTP_401_UNAUTHORIZED:
            # Try refreshing token once
            try:
                github_integration.refresh_access_token()
                access_token = github_integration.integration.sensitive_config.get("access_token")
                response = requests.get(
                    f"https://api.github.com/repos/{org}/{repository}/branches/{branch}",
                    headers={
                        "Accept": "application/vnd.github+json",
                        "Authorization": f"Bearer {access_token}",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    timeout=10,
                )
            except Exception as e:
                logger.warning("Failed to refresh token after 401", error=str(e))

        response.raise_for_status()
        branch_data = response.json()
        return branch_data["commit"]["sha"]

    except requests.RequestException as e:
        logger.exception("Failed to get branch SHA", team_id=team.pk, repository=repository, branch=branch)
        raise GitHubClientError(f"Failed to fetch branch info: {str(e)}")


def get_repository_tree(team: Team, repository: str, sha: str) -> dict[str, Any]:
    """
    Get the complete file tree for a repository at a specific commit.

    Args:
        team: PostHog team
        repository: Repository name (just the repo name, not full path)
        sha: Commit SHA

    Returns:
        GitHub tree response with filtered Python files only

    Raises:
        GitHubIntegrationNotFoundError: If no GitHub integration exists
        GitHubClientError: If GitHub API request fails
    """
    github_integration = get_github_integration(team)
    org = github_integration.organization()
    access_token = github_integration.integration.sensitive_config.get("access_token")

    # Refresh token if needed
    try:
        if github_integration.access_token_expired():
            github_integration.refresh_access_token()
            access_token = github_integration.integration.sensitive_config.get("access_token")
    except Exception as e:
        logger.warning("Failed to refresh GitHub token", error=str(e), team_id=team.pk)

    try:
        response = requests.get(
            f"https://api.github.com/repos/{org}/{repository}/git/trees/{sha}?recursive=1",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
        )

        if response.status_code == status.HTTP_401_UNAUTHORIZED:
            # Try refreshing token once
            try:
                github_integration.refresh_access_token()
                access_token = github_integration.integration.sensitive_config.get("access_token")
                response = requests.get(
                    f"https://api.github.com/repos/{org}/{repository}/git/trees/{sha}?recursive=1",
                    headers={
                        "Accept": "application/vnd.github+json",
                        "Authorization": f"Bearer {access_token}",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    timeout=30,
                )
            except Exception as e:
                logger.warning("Failed to refresh token after 401", error=str(e))

        response.raise_for_status()
        tree_data = response.json()

        # Filter to only include Python files and directories
        filtered_tree = []
        for item in tree_data.get("tree", []):
            if item["type"] == "tree" or (item["type"] == "blob" and item["path"].endswith(".py")):
                filtered_tree.append(item)

        tree_data["tree"] = filtered_tree
        logger.info(
            "Fetched repository tree",
            team_id=team.pk,
            repository=repository,
            sha=sha[:8],
            total_items=len(tree_data.get("tree", [])),
        )

        return tree_data

    except requests.RequestException as e:
        logger.exception("Failed to get repository tree", team_id=team.pk, repository=repository, sha=sha[:8])
        raise GitHubClientError(f"Failed to fetch repository tree: {str(e)}")


def get_file_content(team: Team, repository: str, path: str) -> dict[str, Any]:
    """
    Get the content of a file from a repository.

    Args:
        team: PostHog team
        repository: Repository name (just the repo name, not full path)
        path: File path in repository

    Returns:
        File content data with decoded content

    Raises:
        GitHubIntegrationNotFoundError: If no GitHub integration exists
        GitHubClientError: If GitHub API request fails
    """
    github_integration = get_github_integration(team)
    org = github_integration.organization()
    access_token = github_integration.integration.sensitive_config.get("access_token")

    # Refresh token if needed
    try:
        if github_integration.access_token_expired():
            github_integration.refresh_access_token()
            access_token = github_integration.integration.sensitive_config.get("access_token")
    except Exception as e:
        logger.warning("Failed to refresh GitHub token", error=str(e), team_id=team.pk)

    try:
        response = requests.get(
            f"https://api.github.com/repos/{org}/{repository}/contents/{path}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=10,
        )

        if response.status_code == status.HTTP_404_NOT_FOUND:
            raise GitHubClientError(f"File '{path}' not found in repository '{org}/{repository}'")

        if response.status_code == status.HTTP_401_UNAUTHORIZED:
            # Try refreshing token once
            try:
                github_integration.refresh_access_token()
                access_token = github_integration.integration.sensitive_config.get("access_token")
                response = requests.get(
                    f"https://api.github.com/repos/{org}/{repository}/contents/{path}",
                    headers={
                        "Accept": "application/vnd.github+json",
                        "Authorization": f"Bearer {access_token}",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    timeout=10,
                )
            except Exception as e:
                logger.warning("Failed to refresh token after 401", error=str(e))

        response.raise_for_status()
        file_data = response.json()

        # Decode base64 content
        if file_data.get("encoding") == "base64" and "content" in file_data:
            try:
                decoded_content = base64.b64decode(file_data["content"]).decode("utf-8")
                file_data["content"] = decoded_content
            except Exception as e:
                logger.warning("Failed to decode file content", error=str(e), path=path)

        logger.info("Fetched file content", team_id=team.pk, repository=repository, path=path)
        return file_data

    except requests.RequestException as e:
        logger.exception("Failed to get file content", team_id=team.pk, repository=repository, path=path)
        raise GitHubClientError(f"Failed to fetch file content: {str(e)}")
