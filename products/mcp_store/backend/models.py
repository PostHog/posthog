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

# Catalog categories used by the marketplace UI to group templates. Pinned to a
# finite choice list so the frontend can render predictable filter chips. New
# rows default to "dev" until they're reclassified in the admin.
CATEGORY_CHOICES = [
    ("business", "Business Operations"),
    ("data", "Data & Analytics"),
    ("design", "Design & Content"),
    ("dev", "Developer Tools & APIs"),
    ("infra", "Infrastructure"),
    ("productivity", "Productivity & Collaboration"),
]


class SensitiveConfig(TypedDict, total=False):
    api_key: str
    access_token: str
    refresh_token: str
    token_retrieved_at: int
    expires_in: int
    needs_reauth: bool
    # Set on custom (non-template) OAuth installs. Each user gets their own
    # DCR client so the upstream provider can quarantine a single user without
    # affecting others. `dcr_is_user_provided` is true when the creds came from
    # the install form instead of a DCR handshake.
    dcr_client_id: str
    dcr_client_secret: str
    dcr_is_user_provided: bool


class TemplateOAuthCredentials(TypedDict, total=False):
    client_id: str
    client_secret: str


InstallSource = Literal["posthog", "twig", "posthog-code"]
INSTALL_SOURCE_CHOICES = [("posthog", "posthog"), ("twig", "twig"), ("posthog-code", "posthog-code")]


class MCPServerTemplate(CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    """A curated, pre-registered MCP server. PostHog operators register a real
    OAuth app with the provider ahead of time and paste the client_id /
    client_secret in Django admin. The credentials are shared across every user
    who installs the template — users only get their own per-user access/refresh
    tokens. User-added servers (see MCPServerInstallation without a template
    FK) go through per-user DCR instead."""

    name = models.CharField(max_length=200)
    url = models.URLField(max_length=2048, unique=True)
    docs_url = models.URLField(max_length=2048, blank=True, default="")
    description = models.TextField(blank=True, default="")
    auth_type = models.CharField(max_length=20, choices=AUTH_TYPE_CHOICES, default="oauth")
    icon_key = models.CharField(max_length=100, blank=True, default="")
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="dev")
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
