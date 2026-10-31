from typing import Optional

from posthog.egress.limiter.policies import Priority
from posthog.integrations import IntegrationManager
from posthog.models.integration import GitHubIntegration


def get_github_token(team_id: int, github_integration_id: int) -> Optional[str]:
    integration = IntegrationManager.github.oauth.get(team_id, github_integration_id)
    github_integration = GitHubIntegration(integration, source="tasks_sandbox", priority=Priority.CRITICAL)

    if github_integration.access_token_expired():
        github_integration.refresh_access_token()

    return github_integration.integration.access_token or None


def get_sandbox_name_for_snapshot(github_integration_id: int, repository: str) -> str:
    return f"snapshot-sandbox-{github_integration_id}-{repository.replace('/', '-')}"
