from django.db import models

from posthog.helpers.encrypted_fields import EncryptedJSONField
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

AUTH_TYPE_CHOICES = [
    ("none", "None"),
    ("api_key", "API Key"),
    ("oauth", "OAuth"),
]

OAUTH_KIND_MAP: dict[str, str] = {
    "https://mcp.linear.app/mcp": "linear",
}

RECOMMENDED_SERVERS = [
    {
        "name": "PostHog MCP",
        "url": "https://mcp.posthog.com/mcp",
        "description": "Access PostHog analytics tools including querying events, creating insights, and managing feature flags.",
        "icon_url": "https://posthog.com/brand/posthog-icon.svg",
        "auth_type": "api_key",
    },
    {
        "name": "Linear",
        "url": "https://mcp.linear.app/mcp",
        "description": "Manage Linear issues, projects, and teams directly from your AI agent.",
        "icon_url": "",
        "auth_type": "oauth",
    },
    {
        "name": "Notion",
        "url": "https://mcp.notion.so",
        "description": "Search and manage Notion pages, databases, and knowledge base content.",
        "icon_url": "",
        "auth_type": "oauth",
    },
]


class MCPServer(CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    name = models.CharField(max_length=200)
    url = models.URLField(max_length=2048, unique=True)
    description = models.TextField(blank=True, default="")
    icon_url = models.URLField(max_length=2048, blank=True, default="")
    auth_type = models.CharField(max_length=20, choices=AUTH_TYPE_CHOICES, default="none")
    is_default = models.BooleanField(default=False)
    is_signal_source = models.BooleanField(default=False)
    oauth_metadata = models.JSONField(default=dict, blank=True)
    oauth_client_id = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        db_table = "mcp_store_mcpserver"


class MCPServerInstallation(CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="mcp_server_installations")
    server = models.ForeignKey(MCPServer, on_delete=models.CASCADE, related_name="installations")
    configuration = models.JSONField(default=dict, blank=True)
    sensitive_configuration = EncryptedJSONField(default=dict, blank=True)

    class Meta:
        db_table = "mcp_store_mcpserverinstallation"
        unique_together = [("team", "user", "server")]
