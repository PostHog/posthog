from typing import Optional

from posthog.models.integration import GitHubIntegration, Integration
from posthog.temporal.common.utils import asyncify


@asyncify
def get_github_token(github_integration_id: int) -> Optional[str]:
    integration = Integration.objects.get(id=github_integration_id)
    github_integration = GitHubIntegration(integration)

    if github_integration.access_token_expired():
        github_integration.refresh_access_token()

    return github_integration.integration.access_token or None


def get_sandbox_name_for_task(task_id: str) -> str:
    return f"task-sandbox-{task_id}"
