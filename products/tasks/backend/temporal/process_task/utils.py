from asgiref.sync import sync_to_async

from posthog.models.integration import GitHubIntegration, Integration


async def get_github_token(github_integration_id: int) -> str:
    """Get GitHub access token for an integration."""

    integration = await sync_to_async(Integration.objects.get)(id=github_integration_id)
    github_integration = GitHubIntegration(integration)

    if await sync_to_async(github_integration.access_token_expired)():
        await sync_to_async(github_integration.refresh_access_token)()

    return github_integration.integration.access_token or ""
