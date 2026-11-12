import logging

import requests

from posthog.integrations import IntegrationRecord
from posthog.models.integration import GitLabIntegration, GitLabIntegrationError

logger = logging.getLogger(__name__)

# The sandbox network allowlist and the clone URL cover gitlab.com only.
GITLAB_COM = "https://gitlab.com"


def gitlab_repository_error(integration: IntegrationRecord, repository: str) -> str | None:
    """Why a task cannot work in ``repository`` through ``integration``, or None when it can."""
    gitlab = GitLabIntegration(integration)
    if gitlab.hostname.rstrip("/").lower() != GITLAB_COM:
        return "Coding tasks work with projects on gitlab.com only. Connect a gitlab.com project to continue."
    # The person who connected GitLab shared one project, even when the token can reach more.
    if repository.strip().lower() != (gitlab.project_path or "").lower():
        return (
            f"This GitLab connection covers {gitlab.project_path} only. Connect {repository} as its own GitLab project."
        )
    try:
        token_info = gitlab.credentials.describe()
        if token_info is not None and token_info.missing_task_scopes:
            scopes = ", ".join(token_info.missing_task_scopes)
            return (
                f"The GitLab token is missing the {scopes} scope. Create a token with that scope and connect it again."
            )
        project = gitlab.get_pushable_project(repository)
    except (GitLabIntegrationError, requests.RequestException):
        logger.warning(
            "gitlab_repository_access_check_unavailable",
            exc_info=True,
            extra={"team_id": integration.team_id, "integration_id": integration.id},
        )
        return "Couldn't reach GitLab to check access to this project. Try again in a minute."
    if project is None:
        return (
            f"The GitLab token can't push to {repository}. "
            "Give the token the Developer role or higher on this project, then try again."
        )
    return None
