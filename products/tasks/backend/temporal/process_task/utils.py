from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlparse

from django.conf import settings

from posthog.models.integration import GitHubIntegration, Integration
from posthog.temporal.oauth import PosthogMcpScopes, has_write_scopes


@dataclass(frozen=True)
class McpServerConfig:
    """Configuration for a remote MCP server matching the ACP McpServer schema.

    Matches the CLI --mcpServers JSON format:
    - type: "http" (streamable HTTP) or "sse"
    - name: server identifier
    - url: server endpoint
    - headers: list of {name, value} pairs
    """

    type: str
    name: str
    url: str
    headers: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "name": self.name,
            "url": self.url,
            "headers": self.headers,
        }


def get_sandbox_api_url() -> str:
    return settings.SANDBOX_API_URL or settings.SITE_URL


def get_sandbox_mcp_configs(
    token: str,
    project_id: int,
    *,
    scopes: PosthogMcpScopes = "read_only",
) -> list[McpServerConfig]:
    """Return MCP server configurations for sandbox agents.

    Uses SANDBOX_MCP_URL if explicitly set, otherwise derives it from SITE_URL:
    - app.posthog.com / us.posthog.com → https://mcp.posthog.com/mcp
    - eu.posthog.com → https://mcp-eu.posthog.com/mcp
    - Other hosts → empty list (MCP not available)
    """
    url = _resolve_mcp_url()
    if not url:
        return []
    read_only = not has_write_scopes(scopes)
    headers = [
        {"name": "Authorization", "value": f"Bearer {token}"},
        {"name": "x-posthog-project-id", "value": str(project_id)},
        {"name": "x-posthog-mcp-version", "value": "2"},
        {"name": "x-posthog-read-only", "value": str(read_only).lower()},
    ]
    return [McpServerConfig(type="http", name="posthog", url=url, headers=headers)]


def _resolve_mcp_url() -> str | None:
    if settings.SANDBOX_MCP_URL:
        return settings.SANDBOX_MCP_URL

    site_url = settings.SITE_URL
    if not site_url:
        return None

    hostname = urlparse(site_url).hostname or ""
    if hostname in ("app.posthog.com", "us.posthog.com"):
        return "https://mcp.posthog.com/mcp"
    if hostname == "eu.posthog.com":
        return "https://mcp-eu.posthog.com/mcp"

    return None


def get_github_token(github_integration_id: int) -> Optional[str]:
    integration = Integration.objects.get(id=github_integration_id)
    github_integration = GitHubIntegration(integration)

    if github_integration.access_token_expired():
        github_integration.refresh_access_token()

    return github_integration.integration.access_token or None


def get_sandbox_name_for_task(task_id: str) -> str:
    return f"task-sandbox-{task_id}"


def build_sandbox_environment_variables(
    github_token: str | None,
    access_token: str,
    team_id: int,
    sandbox_environment: Optional[Any] = None,
) -> dict[str, str]:
    """Build the environment variables dict for a sandbox, merging user env vars from SandboxEnvironment.

    User-provided env vars are applied first so system vars always take precedence,
    preventing a malicious SandboxEnvironment from overriding security-critical values.
    """
    from products.tasks.backend.services.connection_token import get_sandbox_jwt_public_key

    env_vars: dict[str, str] = {}

    # Apply user-provided vars first so system vars always take precedence
    if sandbox_environment and sandbox_environment.environment_variables:
        env_vars.update(sandbox_environment.environment_variables)

    if github_token:
        env_vars["GITHUB_TOKEN"] = github_token

    env_vars.update(
        {
            "POSTHOG_PERSONAL_API_KEY": access_token,
            "POSTHOG_API_URL": get_sandbox_api_url(),
            "POSTHOG_PROJECT_ID": str(team_id),
            "JWT_PUBLIC_KEY": get_sandbox_jwt_public_key(),
        }
    )

    if settings.SANDBOX_LLM_GATEWAY_URL:
        env_vars["LLM_GATEWAY_URL"] = settings.SANDBOX_LLM_GATEWAY_URL

    return env_vars
