from typing import TypedDict

from django.db import models

from posthog.helpers.encrypted_fields import EncryptedJSONField
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

AUTH_TYPE_CHOICES = [
    ("none", "None"),
    ("api_key", "API Key"),
    ("oauth", "OAuth"),
]


class SensitiveConfig(TypedDict, total=False):
    api_key: str
    access_token: str
    refresh_token: str
    token_retrieved_at: int
    expires_in: int
    needs_reauth: bool


# TRICKY: this is not a 1:1 mapping to MCPServer objects.
# The URL in RECOMMENDED_SERVERS is the MCP server URL, not the OAuth server URL.
RECOMMENDED_SERVERS = [
    {
        "name": "PostHog MCP",
        "url": "https://mcp.posthog.com/mcp",
        "description": "Access PostHog analytics tools including querying events, creating insights, and managing feature flags.",
        "icon_url": "",
        "auth_type": "api_key",
    },
    {
        "name": "Linear",
        "url": "https://mcp.linear.app/mcp",
        "description": "Manage Linear issues, projects, and teams directly from your AI agent.",
        "icon_url": "",
        "auth_type": "oauth",
        "oauth_provider_kind": "linear",
    },
    {
        "name": "Notion",
        "url": "https://mcp.notion.com/mcp",
        "description": "Search and manage Notion pages, databases, and knowledge base content.",
        "icon_url": "",
        "auth_type": "oauth",
    },
]


class MCPServer(CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    name = models.CharField(max_length=200)
    url = models.URLField(max_length=2048, unique=True)  # OAuth issuer URL
    description = models.TextField(blank=True, default="")
    oauth_provider_kind = models.CharField(max_length=50, blank=True, default="")
    oauth_metadata = models.JSONField(default=dict, blank=True)
    oauth_client_id = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        db_table = "mcp_store_mcpserver"


class MCPServerInstallation(CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="mcp_server_installations")
    server = models.ForeignKey(MCPServer, on_delete=models.CASCADE, related_name="installations", null=True, blank=True)
    display_name = models.CharField(max_length=200, blank=True, default="")
    url = models.URLField(max_length=2048, default="")
    description = models.TextField(blank=True, default="")
    auth_type = models.CharField(max_length=20, choices=AUTH_TYPE_CHOICES, default="none")
    configuration = models.JSONField(default=dict, blank=True)
    sensitive_configuration = EncryptedJSONField(default=dict, blank=True)

    class Meta:
        db_table = "mcp_store_mcpserverinstallation"
        unique_together = [("team", "user", "url")]
