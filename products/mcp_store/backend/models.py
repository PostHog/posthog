from typing import Literal, TypedDict

from django.db import models

from posthog.helpers.encrypted_fields import EncryptedJSONField
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

AUTH_TYPE_CHOICES = [
    ("api_key", "API Key"),
    ("oauth", "OAuth"),
]

APPROVAL_STATES = [
    ("approved", "Approved"),
    ("needs_approval", "Needs approval"),
    ("do_not_use", "Do not use"),
]


class SensitiveConfig(TypedDict, total=False):
    api_key: str
    access_token: str
    refresh_token: str
    token_retrieved_at: int
    expires_in: int
    needs_reauth: bool
    # Set on custom (non-template) OAuth installs.
    # `dcr_is_user_provided` is true when the creds came from
    # the install form instead of a DCR handshake.
    dcr_client_id: str
    dcr_client_secret: str
    dcr_is_user_provided: bool


class TemplateOAuthCredentials(TypedDict, total=False):
    client_id: str
    client_secret: str


InstallSource = Literal["posthog", "twig", "posthog-code"]
INSTALL_SOURCE_CHOICES = [("posthog", "posthog"), ("twig", "twig"), ("posthog-code", "posthog-code")]


# TRICKY: this is not a 1:1 mapping to MCPServer objects.
# The URL in RECOMMENDED_SERVERS is the MCP server URL, not the OAuth server URL.
RECOMMENDED_SERVERS = [
    {
        "name": "Attio",
        "url": "https://mcp.attio.com/mcp",
        "description": "Manage Attio CRM contacts, companies, and deals.",
        "auth_type": "oauth",
    },
    {
        "name": "Canva",
        "url": "https://mcp.canva.com/mcp",
        "description": "Create, edit, and manage Canva designs and assets.",
        "auth_type": "oauth",
    },
    {
        "name": "Atlassian",
        "url": "https://mcp.atlassian.com/v1/mcp",
        "description": "Integrate with Atlassian products like Jira and Confluence.",
        "auth_type": "oauth",
    },
    {
        "name": "Linear",
        "url": "https://mcp.linear.app/mcp",
        "description": "Manage Linear issues, projects, and teams.",
        "auth_type": "oauth",
    },
    {
        "name": "Monday",
        "url": "https://mcp.monday.com/mcp",
        "description": "Manage Monday.com boards, items, and workflows.",
        "auth_type": "oauth",
    },
    {
        "name": "Notion",
        "url": "https://mcp.notion.com/mcp",
        "description": "Search and manage Notion pages, databases, and knowledge base content.",
        "auth_type": "oauth",
    },
]


class MCPServer(CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    """Legacy shared-DCR server record. Being superseded by MCPServerTemplate (for
    curated pre-registered apps) and by per-installation creds stored in
    MCPServerInstallation.sensitive_configuration (for user-added servers).
    Kept during rollout; slated for removal once data migration completes."""

    name = models.CharField(max_length=200)
    url = models.URLField(max_length=2048, unique=True)  # OAuth issuer URL
    description = models.TextField(blank=True, default="")
    oauth_metadata = models.JSONField(default=dict, blank=True)
    oauth_client_id = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        db_table = "mcp_store_mcpserver"


class MCPServerTemplate(CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    """A curated, pre-registered MCP server. PostHog operators register a real
    OAuth app with the provider ahead of time and paste the client_id /
    client_secret in Django admin. The credentials are shared across every user
    who installs the template — users only get their own per-user access/refresh
    tokens. User-added servers (see MCPServerInstallation without a template
    FK) go through per-user DCR instead."""

    name = models.CharField(max_length=200)
    url = models.URLField(max_length=2048, unique=True)
    description = models.TextField(blank=True, default="")
    auth_type = models.CharField(max_length=20, choices=AUTH_TYPE_CHOICES, default="oauth")
    icon_key = models.CharField(max_length=100, blank=True, default="")
    oauth_issuer_url = models.URLField(max_length=2048, blank=True, default="")
    oauth_metadata = models.JSONField(default=dict, blank=True)
    oauth_credentials = EncryptedJSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=False)

    class Meta:
        db_table = "mcp_store_mcpservertemplate"
        indexes = [models.Index(fields=["is_active"])]


class MCPServerInstallation(CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="mcp_server_installations")
    # Legacy FK — populated before the template refactor. New code reads `template` instead.
    server = models.ForeignKey(MCPServer, on_delete=models.CASCADE, related_name="installations", null=True, blank=True)
    template = models.ForeignKey(
        MCPServerTemplate, on_delete=models.SET_NULL, related_name="installations", null=True, blank=True
    )
    display_name = models.CharField(max_length=200, blank=True, default="")
    url = models.URLField(max_length=2048, default="")
    description = models.TextField(blank=True, default="")
    auth_type = models.CharField(max_length=20, choices=AUTH_TYPE_CHOICES, default="oauth")
    is_enabled = models.BooleanField(default=True)
    # Cached per-installation OAuth metadata for custom (non-template) installs. Non-secret.
    oauth_issuer_url = models.URLField(max_length=2048, blank=True, default="")
    oauth_metadata = models.JSONField(default=dict, blank=True)
    sensitive_configuration = EncryptedJSONField(default=dict, blank=True)

    class Meta:
        db_table = "mcp_store_mcpserverinstallation"
        unique_together = [("team", "user", "url")]


class MCPServerInstallationTool(CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    """Per-installation cache of the tools an MCP server exposes, with a
    per-user approval state. Because MCPServerInstallation is already scoped
    to (team, user, url), hanging tools off the installation gives us per-user
    storage for free."""

    installation = models.ForeignKey(MCPServerInstallation, on_delete=models.CASCADE, related_name="tools")
    tool_name = models.CharField(max_length=200)
    display_name = models.CharField(max_length=200, blank=True, default="")
    description = models.TextField(blank=True, default="")
    input_schema = models.JSONField(default=dict, blank=True)
    approval_state = models.CharField(max_length=20, choices=APPROVAL_STATES, default="needs_approval")
    last_seen_at = models.DateTimeField()
    # Set when the tool is absent from a fresh tools/list. Cleared on reappearance.
    # Kept around so approval_state survives a temporary disappearance.
    removed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "mcp_store_mcpserverinstallationtool"
        unique_together = [("installation", "tool_name")]
        indexes = [
            models.Index(fields=["installation", "approval_state"]),
            models.Index(fields=["installation", "removed_at"]),
        ]


class MCPOAuthState(CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    installation = models.ForeignKey(MCPServerInstallation, on_delete=models.CASCADE, related_name="oauth_states")
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    # Legacy FK for the DCR-keyed server. New flows populate `template` instead (or
    # leave it null for custom installs, which resolve creds from the installation itself).
    server = models.ForeignKey(MCPServer, on_delete=models.CASCADE, related_name="oauth_states", null=True, blank=True)
    template = models.ForeignKey(
        MCPServerTemplate, on_delete=models.CASCADE, related_name="oauth_states", null=True, blank=True
    )
    install_source = models.CharField(max_length=20, choices=INSTALL_SOURCE_CHOICES, default="posthog")
    posthog_code_callback_url = models.TextField(blank=True, default="", db_column="twig_callback_url")
    pkce_verifier = models.CharField(max_length=255, blank=True, default="")
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "mcp_store_mcpoauthstate"
        indexes = [
            models.Index(fields=["expires_at"]),
            models.Index(fields=["consumed_at"]),
        ]
