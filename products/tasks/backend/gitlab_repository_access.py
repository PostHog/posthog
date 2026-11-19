import time
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
    deadline = time.monotonic() + 10

    def remaining() -> float:
        timeout = deadline - time.monotonic()
        if timeout <= 0:
            raise GitLabIntegrationError("GitLab access check timed out")
        return timeout

    try:
        token_info = gitlab.credentials.describe(timeout=remaining())
        if token_info is not None and token_info.missing_task_scopes:
            scopes = ", ".join(token_info.missing_task_scopes)
            return (
                f"The GitLab token is missing the {scopes} scope. Create a token with that scope and connect it again."
            )
        project = gitlab.get_pushable_project(repository, timeout=remaining())
        bound = project is not None and gitlab.token_reaches_only_connected_project(timeout=remaining())
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
    if not bound:
        return (
            "Coding tasks need a project access token for this project, because the agent holds the token "
            "while it works. Personal and group tokens can reach more than this project. "
            f"Create a project access token in {gitlab.project_path} and connect GitLab again."
        )
    return None
