from typing import Literal, TypedDict
from urllib.parse import urlparse

from django.db import models
from django.db.models import Q

from posthog.helpers.encrypted_fields import EncryptedJSONField
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
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

SCOPE_CHOICES = [
    ("personal", "Personal"),
    ("shared", "Shared"),
]

# How a gateway server authenticates its callers: everyone rides one shared
# credential, or each member connects their own account.
GATEWAY_AUTH_MODE_CHOICES = [
    ("individual", "Individual accounts"),
    ("shared", "Shared credential"),
]

SERVICE_ACCOUNT_STATUS_CHOICES = [
    ("active", "Active"),
    ("paused", "Paused"),
]

# Team-level policy baselines. They derive a default per-tool state for tools
# that have no explicit policy row (see policy.member_preset_team_state).
POLICY_PRESET_CHOICES = [
    ("allow", "Allow all"),
    ("user", "Member decides"),
    ("ask", "Ask for destructive"),
    ("block", "Block destructive"),
]

POLICY_SCOPE_TYPE_CHOICES = [
    ("team", "Team default"),
    ("member", "Member"),
    ("agent", "Agent"),
]

ORG_RULE_APPLIES_TO_CHOICES = [
    ("everyone", "Everyone"),
    ("members", "Members"),
    ("agents", "Agents"),
]

ORG_RULE_EFFECT_CHOICES = [
    ("needs_approval", "Require approval"),
    ("do_not_use", "Block"),
]

# How the gateway decided a proxied tool call. "pending" is an agent call that
# hit a needs_approval tool and was rejected awaiting a human.
AUDIT_DECISION_CHOICES = [
    ("auto", "Auto-approved"),
    ("approved", "Approved"),
    ("pending", "Awaiting approval"),
    ("blocked", "Blocked"),
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
    dcr_token_endpoint_auth_method: str
    dcr_is_user_provided: bool


class TemplateOAuthCredentials(TypedDict, total=False):
    client_id: str
    client_secret: str


InstallSource = Literal["posthog", "twig", "posthog-code"]
INSTALL_SOURCE_CHOICES = [("posthog", "posthog"), ("twig", "twig"), ("posthog-code", "posthog-code")]


def normalize_mcp_template_icon_key(value: str) -> str:
    """Lowercase, replace runs of whitespace with a single underscore (slug fragment)."""
    return "_".join((value or "").lower().split())


def normalize_mcp_icon_domain(value: str) -> str:
    """Lowercase hostname, no scheme/path/query/port — the id logo.dev keys brand icons on."""
    value = (value or "").strip().lower()
    if not value:
        return ""
    # urlparse only treats the leading segment as a host when a netloc separator is present.
    if "//" not in value:
        value = f"//{value}"
    return (urlparse(value).hostname or "").rstrip(".")


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
    # Deprecated: icons resolve from icon_domain via logo.dev; the column drop is a follow-up.
    icon_key = models.CharField(max_length=100, blank=True, default="")
    # The vendor's brand domain (e.g. "linear.app") — resolved to an icon at render time via
    # the logo.dev proxy, so catalog entries need no committed image assets.
    icon_domain = models.CharField(max_length=253, blank=True, default="")
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="dev", db_default="dev")
    oauth_issuer_url = models.URLField(max_length=2048, blank=True, default="")
    oauth_metadata = models.JSONField(default=dict, blank=True)
    oauth_credentials = EncryptedJSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=False)

    def save(self, *args, **kwargs) -> None:
        update_fields = kwargs.get("update_fields")
        if update_fields is None or "icon_key" in update_fields:
            self.icon_key = normalize_mcp_template_icon_key(self.icon_key or "")
        if update_fields is None or "icon_domain" in update_fields:
            self.icon_domain = normalize_mcp_icon_domain(self.icon_domain or "")
        super().save(*args, **kwargs)

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
    # db_default keeps a real Postgres DEFAULT so inserts from code predating
    # this column (old pods during a rolling deploy) don't hit the NOT NULL.
    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default="personal", db_default="personal")
    # Cached per-installation OAuth metadata for custom (non-template) installs. Non-secret.
    oauth_issuer_url = models.URLField(max_length=2048, blank=True, default="")
    oauth_metadata = models.JSONField(default=dict, blank=True)
    sensitive_configuration = EncryptedJSONField(default=dict, blank=True)
    # The team-level gateway registration this credential belongs to. Null for
    # rows that predate the gateway until the backfill links them; the proxy
    # falls back to pre-gateway behavior when unset.
    gateway_server = models.ForeignKey(
        "MCPGatewayServer", on_delete=models.SET_NULL, related_name="installations", null=True, blank=True
    )
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "mcp_store_mcpserverinstallation"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "user", "url"],
                condition=Q(scope="personal"),
                name="uniq_personal_install",
            ),
            models.UniqueConstraint(
                fields=["team", "url"],
                condition=Q(scope="shared"),
                name="uniq_shared_install",
            ),
        ]


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
    # In-app path to land back on after the OAuth round-trip (e.g. the gateway
    # page that initiated the connect). Validated as a same-app relative path
    # before any redirect — see `_is_valid_web_return_path`.
    web_return_path = models.TextField(blank=True, default="")
    pkce_verifier = models.CharField(max_length=255, blank=True, default="")
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "mcp_store_mcpoauthstate"
        indexes = [
            models.Index(fields=["expires_at"]),
            models.Index(fields=["consumed_at"]),
        ]


class TeamMCPGatewayConfig(TeamScopedRootMixin, UUIDModel):
    """Team-wide gateway settings (a Team extension — not fields on Team)."""

    team = models.OneToOneField(
        "posthog.Team", on_delete=models.CASCADE, related_name="mcp_gateway_config", db_constraint=False
    )
    allow_custom_servers = models.BooleanField(default=True)
    # Blank until an admin applies a preset from Team settings; the policy
    # engine treats blank as "no baseline".
    member_default_preset = models.CharField(max_length=20, choices=POLICY_PRESET_CHOICES, blank=True, default="")
    agent_default_preset = models.CharField(max_length=20, choices=POLICY_PRESET_CHOICES, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "mcp_store_teammcpgatewayconfig"


class MCPGatewayServer(TeamScopedRootMixin, UUIDModel):
    """A team-level registration of one MCP server URL in the gateway.

    Everything the gateway controls hangs off this row: enablement, per-scope
    tool policies, agent access, member revocations, and the audit trail.
    Credentials stay on `MCPServerInstallation` rows that point here."""

    team = models.ForeignKey(
        "posthog.Team", on_delete=models.CASCADE, related_name="gateway_servers", db_constraint=False
    )
    name = models.CharField(max_length=200)
    url = models.URLField(max_length=2048)
    description = models.TextField(blank=True, default="")
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="dev")
    auth_mode = models.CharField(max_length=20, choices=GATEWAY_AUTH_MODE_CHOICES, default="individual")
    # Team-member availability. Agent access is controlled independently by
    # explicit MCPServiceAccountServerAccess grants.
    is_team_enabled = models.BooleanField(default=True)
    # Only meaningful for shared-credential servers: whether members may also
    # connect their own account on top of the shared one.
    allow_personal_connections = models.BooleanField(default=True)
    template = models.ForeignKey(
        MCPServerTemplate, on_delete=models.SET_NULL, related_name="gateway_servers", null=True, blank=True
    )
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "mcp_store_mcpgatewayserver"
        constraints = [
            models.UniqueConstraint(fields=["team", "url"], name="uniq_gateway_server_per_team_url"),
        ]


class MCPMemberServerRevocation(TeamScopedRootMixin, UUIDModel):
    """An admin turned one server off for one member. Presence = revoked."""

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    gateway_server = models.ForeignKey(MCPGatewayServer, on_delete=models.CASCADE, related_name="member_revocations")
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    revoked_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "mcp_store_mcpmemberserverrevocation"
        constraints = [
            models.UniqueConstraint(fields=["gateway_server", "user"], name="uniq_member_server_revocation"),
        ]


class MCPOrgRule(TeamScopedRootMixin, UUIDModel):
    """A team guardrail evaluated before any scope policy. A matching enabled
    rule locks the tool's state for its audience — no scope can loosen it."""

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="org_rules", db_constraint=False)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    applies_to = models.CharField(max_length=20, choices=ORG_RULE_APPLIES_TO_CHOICES, default="everyone")
    effect = models.CharField(max_length=20, choices=ORG_RULE_EFFECT_CHOICES, default="do_not_use")
    # fnmatch-style pattern matched against the tool name (e.g. "delete_*" or
    # "*"). Blank means the rule matches destructive tools heuristically —
    # see policy.is_destructive_tool.
    tool_pattern = models.CharField(max_length=400, blank=True, default="")
    enabled = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "mcp_store_mcporgrule"


class MCPServiceAccount(TeamScopedRootMixin, UUIDModel):
    """A fixed PostHog agent identity with independent MCP access policies."""

    team = models.ForeignKey(
        "posthog.Team", on_delete=models.CASCADE, related_name="mcp_service_accounts", db_constraint=False
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    # Stable internal identity handle shown in audit trails.
    handle = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=SERVICE_ACCOUNT_STATUS_CHOICES, default="active")
    # Reserved unique identity material for the built-in catalog. Runtime
    # authentication uses short-lived signed tokens instead.
    token_hash = models.CharField(max_length=128, unique=True)
    token_mask = models.CharField(max_length=64, blank=True, default="")
    last_active_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "mcp_store_mcpserviceaccount"
        constraints = [
            models.UniqueConstraint(fields=["team", "handle"], name="uniq_service_account_handle_per_team"),
        ]


class MCPServiceAccountServerAccess(TeamScopedRootMixin, UUIDModel):
    """Grant row: this agent may call this gateway server."""

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    service_account = models.ForeignKey(MCPServiceAccount, on_delete=models.CASCADE, related_name="server_access")
    gateway_server = models.ForeignKey(MCPGatewayServer, on_delete=models.CASCADE, related_name="agent_access")
    granted_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs) -> None:
        # Join rows are always created via their parents; derive the tenant key
        # so get_or_create call sites don't have to thread it through.
        if not self.team_id and self.gateway_server_id:
            self.team_id = self.gateway_server.team_id
        super().save(*args, **kwargs)

    class Meta:
        db_table = "mcp_store_mcpserviceaccountserveraccess"
        constraints = [
            models.UniqueConstraint(fields=["service_account", "gateway_server"], name="uniq_agent_server_access"),
        ]


class MCPToolPolicy(TeamScopedRootMixin, UUIDModel):
    """One tool's state for one scope: the team default, one member, or one
    agent. Resolution order lives in policy.PolicyContext."""

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    gateway_server = models.ForeignKey(MCPGatewayServer, on_delete=models.CASCADE, related_name="tool_policies")
    tool_name = models.CharField(max_length=200)
    scope_type = models.CharField(max_length=20, choices=POLICY_SCOPE_TYPE_CHOICES)
    scope_user = models.ForeignKey(
        "posthog.User", on_delete=models.CASCADE, null=True, blank=True, related_name="+", db_constraint=False
    )
    scope_service_account = models.ForeignKey(
        MCPServiceAccount, on_delete=models.CASCADE, null=True, blank=True, related_name="tool_policies"
    )
    state = models.CharField(max_length=20, choices=APPROVAL_STATES, default="needs_approval")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs) -> None:
        if not self.team_id and self.gateway_server_id:
            self.team_id = self.gateway_server.team_id
        super().save(*args, **kwargs)

    class Meta:
        db_table = "mcp_store_mcptoolpolicy"
        indexes = [models.Index(fields=["gateway_server", "scope_type"])]
        constraints = [
            models.UniqueConstraint(
                fields=["gateway_server", "tool_name"],
                condition=Q(scope_type="team"),
                name="uniq_team_tool_policy",
            ),
            models.UniqueConstraint(
                fields=["gateway_server", "tool_name", "scope_user"],
                condition=Q(scope_type="member"),
                name="uniq_member_tool_policy",
            ),
            models.UniqueConstraint(
                fields=["gateway_server", "tool_name", "scope_service_account"],
                condition=Q(scope_type="agent"),
                name="uniq_agent_tool_policy",
            ),
            models.CheckConstraint(
                check=(
                    Q(scope_type="team", scope_user__isnull=True, scope_service_account__isnull=True)
                    | Q(scope_type="member", scope_user__isnull=False, scope_service_account__isnull=True)
                    | Q(scope_type="agent", scope_user__isnull=True, scope_service_account__isnull=False)
                ),
                name="tool_policy_scope_matches_type",
            ),
        ]


class MCPAuditEvent(TeamScopedRootMixin, UUIDModel):
    """One proxied tool call and how the gateway decided it. Metadata only —
    never request/response bodies. Actor fields are denormalized so the trail
    survives account or server deletion."""

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    gateway_server = models.ForeignKey(
        MCPGatewayServer, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_events"
    )
    installation = models.ForeignKey(
        MCPServerInstallation, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    actor_user = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    actor_service_account = models.ForeignKey(
        MCPServiceAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_events"
    )
    actor_label = models.CharField(max_length=254, blank=True, default="")
    server_name = models.CharField(max_length=200, blank=True, default="")
    tool_name = models.CharField(max_length=200, blank=True, default="")
    decision = models.CharField(max_length=20, choices=AUDIT_DECISION_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "mcp_store_mcpauditevent"
        indexes = [
            models.Index(fields=["team", "-created_at"]),
            models.Index(fields=["team", "decision", "-created_at"]),
            models.Index(fields=["team", "actor_service_account", "-created_at"]),
        ]
