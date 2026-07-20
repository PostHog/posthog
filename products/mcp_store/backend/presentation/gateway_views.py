"""Gateway API — the team control plane for MCP servers.

Registrations (`MCPGatewayServer`) are the unit everything hangs off:
enablement, per-scope tool policies, agent access, member revocations, org
rules, and the audit log. Personal/shared credentials stay on
`MCPServerInstallation` (see views.py); this module only adds the team layer.
"""

from typing import Any, cast

from django.db.models import Count, Prefetch, Q, QuerySet
from django.utils.text import slugify

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field, extend_schema_serializer
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.models.organization import OrganizationMembership
from posthog.models.utils import generate_random_token, hash_key_value

from ..models import (
    APPROVAL_STATES,
    POLICY_PRESET_CHOICES,
    POLICY_SCOPE_TYPE_CHOICES,
    SERVICE_ACCOUNT_STATUS_CHOICES,
    MCPAuditEvent,
    MCPGatewayServer,
    MCPMemberServerRevocation,
    MCPOrgRule,
    MCPServerInstallation,
    MCPServerInstallationTool,
    MCPServiceAccount,
    MCPServiceAccountServerAccess,
    MCPToolPolicy,
    TeamMCPGatewayConfig,
)
from ..policy import GatewayCaller, PolicyContext

logger = structlog.get_logger(__name__)

GATEWAY_TOKEN_PREFIX = "mcp_gw_"

RESOLVED_DECIDED_BY_CHOICES = ["rule", "scope", "team", "preset", "legacy", "default"]

AUDIT_QUICK_FILTER_CHOICES = ["all", "agents", "approvals", "blocked"]


def generate_gateway_token() -> tuple[str, str, str]:
    """Returns (raw_token, secure_hash, mask). The raw token is shown once."""
    raw = GATEWAY_TOKEN_PREFIX + generate_random_token(32)
    return raw, hash_key_value(raw), f"{GATEWAY_TOKEN_PREFIX}...{raw[-4:]}"


def get_gateway_config(team_id: int) -> TeamMCPGatewayConfig | None:
    return TeamMCPGatewayConfig.objects.for_team(team_id).first()


class GatewayAdminMixin:
    """Admin gate shared by gateway viewsets.

    Mirrors MCPServerInstallationViewSet._is_project_admin: organization
    admins/owners, or users explicitly granted admin on this project.
    `explicit=True` keeps open-project defaults from making every member an
    effective admin.
    """

    def _is_project_admin(self) -> bool:
        if self.user_access_control.is_organization_admin:  # type: ignore[attr-defined]
            return True
        return bool(
            self.user_access_control.check_access_level_for_object(self.team, "admin", explicit=True)  # type: ignore[attr-defined]
        )

    def _require_project_admin(self) -> None:
        if not self._is_project_admin():
            raise PermissionDenied("Only project admins can manage the MCP gateway.")


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


class GatewayConnectionSerializer(serializers.Serializer):
    """One member's personal connection to a gateway server."""

    installation_id = serializers.UUIDField(help_text="Installation row backing this connection.")
    user = UserBasicSerializer(help_text="The member who connected.")
    last_used_at = serializers.DateTimeField(
        allow_null=True, help_text="When this connection last proxied a tool call. Null if never used."
    )
    pending_oauth = serializers.BooleanField(help_text="True when the OAuth round-trip has not completed yet.")
    needs_reauth = serializers.BooleanField(help_text="True when the stored token was invalidated and needs reauth.")


class GatewayYourConnectionSerializer(serializers.Serializer):
    """The requesting user's own connection to a gateway server."""

    installation_id = serializers.UUIDField(help_text="The caller's installation row for this server.")
    scope = serializers.ChoiceField(
        choices=["personal", "shared"], help_text="Whether the caller connects personally or via the shared credential."
    )
    is_enabled = serializers.BooleanField(help_text="Per-connection switch — false when self-disabled.")
    pending_oauth = serializers.BooleanField(help_text="True when the OAuth round-trip has not completed yet.")
    needs_reauth = serializers.BooleanField(help_text="True when the stored token was invalidated and needs reauth.")
    last_used_at = serializers.DateTimeField(
        allow_null=True, help_text="When the caller last proxied a call through this connection."
    )


class GatewaySharedCredentialSerializer(serializers.Serializer):
    """The admin-managed shared credential of a shared-auth server."""

    installation_id = serializers.UUIDField(help_text="Shared installation row holding the credential.")
    managed_by = UserBasicSerializer(allow_null=True, help_text="Admin who connected the shared credential.")
    is_enabled = serializers.BooleanField(help_text="Whether the shared credential is enabled.")
    pending_oauth = serializers.BooleanField(help_text="True when the shared credential has not finished OAuth.")
    needs_reauth = serializers.BooleanField(help_text="True when the shared credential needs re-authentication.")
    last_used_at = serializers.DateTimeField(
        allow_null=True, help_text="When the shared credential last proxied a call."
    )


class GatewayAgentAccessSerializer(serializers.Serializer):
    """One agent's access to a gateway server."""

    service_account_id = serializers.UUIDField(help_text="Service account granted access.")
    name = serializers.CharField(help_text="Agent display name.")
    handle = serializers.CharField(help_text="Agent identity handle, e.g. svc-support.")
    status = serializers.ChoiceField(
        choices=SERVICE_ACCOUNT_STATUS_CHOICES, help_text="active, or paused (all access off)."
    )
    last_active_at = serializers.DateTimeField(allow_null=True, help_text="When the agent last made a call.")
    granted_by = UserBasicSerializer(allow_null=True, help_text="Admin who shared this server with the agent.")


def _installation_pending_oauth(installation: MCPServerInstallation) -> bool:
    if installation.auth_type != "oauth":
        return False
    return not (installation.sensitive_configuration or {}).get("access_token")


def _installation_needs_reauth(installation: MCPServerInstallation) -> bool:
    if installation.auth_type != "oauth":
        return False
    return bool((installation.sensitive_configuration or {}).get("needs_reauth"))


def _connection_payload(installation: MCPServerInstallation) -> dict[str, Any]:
    return {
        "installation_id": installation.id,
        "user": UserBasicSerializer(installation.user).data,
        "last_used_at": installation.last_used_at,
        "pending_oauth": _installation_pending_oauth(installation),
        "needs_reauth": _installation_needs_reauth(installation),
    }


class MCPGatewayServerSerializer(serializers.ModelSerializer):
    """A server registered in the team's gateway, with connection summary."""

    icon_key = serializers.CharField(
        source="template.icon_key",
        read_only=True,
        default="",
        help_text="Lowercase key from the linked template for brand icons. Empty for custom servers.",
    )
    docs_url = serializers.CharField(
        source="template.docs_url", read_only=True, default="", help_text="Documentation URL from the template."
    )
    template_id = serializers.UUIDField(
        source="template.id", read_only=True, allow_null=True, default=None, help_text="Linked catalog template."
    )
    created_by = UserBasicSerializer(read_only=True, help_text="Who registered the server.")
    tool_count = serializers.SerializerMethodField(help_text="Number of live tools known for this server.")
    connections = serializers.SerializerMethodField(help_text="Members with a personal connection to this server.")
    your_connection = serializers.SerializerMethodField(
        help_text="The requesting user's own connection, or null when not connected."
    )
    shared_credential = serializers.SerializerMethodField(
        help_text="Shared credential details when auth_mode is shared, else null."
    )
    agents = serializers.SerializerMethodField(help_text="Agents this server is shared with.")
    revoked_user_ids = serializers.SerializerMethodField(
        help_text="Ids of members whose access an admin has turned off."
    )
    is_revoked_for_you = serializers.SerializerMethodField(
        help_text="True when an admin has turned this server off for the requesting user."
    )

    class Meta:
        model = MCPGatewayServer
        fields = [
            "id",
            "name",
            "url",
            "description",
            "category",
            "auth_mode",
            "is_team_enabled",
            "allow_personal_connections",
            "icon_key",
            "docs_url",
            "template_id",
            "tool_count",
            "connections",
            "your_connection",
            "shared_credential",
            "agents",
            "revoked_user_ids",
            "is_revoked_for_you",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "name",
            "url",
            "description",
            "category",
            "auth_mode",
            "is_team_enabled",
            "allow_personal_connections",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(serializers.IntegerField())
    def get_tool_count(self, obj: MCPGatewayServer) -> int:
        annotated = getattr(obj, "tool_count_annotated", None)
        if annotated is not None:
            return annotated
        return (
            MCPServerInstallationTool.objects.filter(installation__gateway_server=obj, removed_at__isnull=True)
            .values("tool_name")
            .distinct()
            .count()
        )

    @extend_schema_field(GatewayConnectionSerializer(many=True))
    def get_connections(self, obj: MCPGatewayServer) -> list[dict[str, Any]]:
        return [
            _connection_payload(installation)
            for installation in obj.installations.all()
            if installation.scope == "personal"
        ]

    @extend_schema_field(GatewayYourConnectionSerializer(allow_null=True))
    def get_your_connection(self, obj: MCPGatewayServer) -> dict[str, Any] | None:
        request = self.context.get("request")
        if request is None:
            return None
        own = [installation for installation in obj.installations.all() if installation.user_id == request.user.id]
        # A personal connection wins over owning the shared credential.
        own.sort(key=lambda installation: installation.scope != "personal")
        if not own:
            return None
        installation = own[0]
        return {
            "installation_id": installation.id,
            "scope": installation.scope,
            "is_enabled": installation.is_enabled,
            "pending_oauth": _installation_pending_oauth(installation),
            "needs_reauth": _installation_needs_reauth(installation),
            "last_used_at": installation.last_used_at,
        }

    @extend_schema_field(GatewaySharedCredentialSerializer(allow_null=True))
    def get_shared_credential(self, obj: MCPGatewayServer) -> dict[str, Any] | None:
        if obj.auth_mode != "shared":
            return None
        shared = [installation for installation in obj.installations.all() if installation.scope == "shared"]
        if not shared:
            return None
        installation = shared[0]
        return {
            "installation_id": installation.id,
            "managed_by": UserBasicSerializer(installation.user).data if installation.user else None,
            "is_enabled": installation.is_enabled,
            "pending_oauth": _installation_pending_oauth(installation),
            "needs_reauth": _installation_needs_reauth(installation),
            "last_used_at": installation.last_used_at,
        }

    @extend_schema_field(GatewayAgentAccessSerializer(many=True))
    def get_agents(self, obj: MCPGatewayServer) -> list[dict[str, Any]]:
        return [
            {
                "service_account_id": access.service_account_id,
                "name": access.service_account.name,
                "handle": access.service_account.handle,
                "status": access.service_account.status,
                "last_active_at": access.service_account.last_active_at,
                "granted_by": UserBasicSerializer(access.granted_by).data if access.granted_by else None,
            }
            for access in obj.agent_access.all()
        ]

    @extend_schema_field(serializers.ListField(child=serializers.IntegerField()))
    def get_revoked_user_ids(self, obj: MCPGatewayServer) -> list[int]:
        return [revocation.user_id for revocation in obj.member_revocations.all()]

    @extend_schema_field(serializers.BooleanField())
    def get_is_revoked_for_you(self, obj: MCPGatewayServer) -> bool:
        request = self.context.get("request")
        if request is None:
            return False
        return any(revocation.user_id == request.user.id for revocation in obj.member_revocations.all())


class MCPGatewayServerUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = MCPGatewayServer
        fields = ["name", "description", "category", "is_team_enabled", "allow_personal_connections"]
        extra_kwargs = {
            "name": {"required": False, "help_text": "Display name shown across the gateway."},
            "description": {"required": False, "help_text": "Short description shown on server cards."},
            "category": {"required": False, "help_text": "Catalog category used for filter chips."},
            "is_team_enabled": {
                "required": False,
                "help_text": "Master switch — off means members and agents can neither see nor call the server.",
            },
            "allow_personal_connections": {
                "required": False,
                "help_text": "For shared-credential servers: whether members may also connect their own account.",
            },
        }


class ToolPolicyEntrySerializer(serializers.Serializer):
    tool_name = serializers.CharField(help_text="Tool to set the policy for.")
    policy_state = serializers.ChoiceField(choices=APPROVAL_STATES, help_text="State to apply for this scope.")


class GatewayPoliciesQuerySerializer(serializers.Serializer):
    scope_type = serializers.ChoiceField(
        choices=POLICY_SCOPE_TYPE_CHOICES,
        required=False,
        default="team",
        help_text="Which scope to resolve: the team default, one member, or one agent.",
    )
    scope_user_id = serializers.IntegerField(
        required=False, help_text="Member scope target. Defaults to the requesting user."
    )
    scope_service_account_id = serializers.UUIDField(
        required=False, help_text="Agent scope target. Required when scope_type is agent."
    )


class GatewayPoliciesUpsertSerializer(GatewayPoliciesQuerySerializer):
    policies = ToolPolicyEntrySerializer(many=True, help_text="Per-tool states to upsert for the scope.")


class ResolvedToolPolicySerializer(serializers.Serializer):
    """One tool with its effective policy for the requested scope."""

    tool_name = serializers.CharField(help_text="Tool name as exposed by the upstream server.")
    description = serializers.CharField(allow_blank=True, help_text="Tool description from the upstream server.")
    policy_state = serializers.ChoiceField(choices=APPROVAL_STATES, help_text="Effective state for the scope.")
    team_state = serializers.ChoiceField(
        choices=APPROVAL_STATES,
        allow_null=True,
        help_text="What the team-level chain (row or preset) yields, ignoring the scope. Null when the team imposes nothing.",
    )
    locked = serializers.BooleanField(
        help_text="True when the requester can't change this row (rule match, or admin-imposed for a member)."
    )
    decided_by = serializers.ChoiceField(
        choices=RESOLVED_DECIDED_BY_CHOICES, help_text="Which policy layer decided the state."
    )
    rule_name = serializers.CharField(allow_blank=True, help_text="Matching org rule name, when decided_by is rule.")
    rule_description = serializers.CharField(
        allow_blank=True, help_text="Matching org rule description, when decided_by is rule."
    )


# many=False keeps spectacular from wrapping this in an array for the `list` action,
# which returns the team's single config object rather than a collection.
@extend_schema_serializer(many=False)
class TeamMCPGatewayConfigSerializer(serializers.ModelSerializer):
    is_admin = serializers.SerializerMethodField(
        help_text="Whether the requesting user can administer the gateway (org admin or explicit project admin)."
    )

    class Meta:
        model = TeamMCPGatewayConfig
        fields = ["allow_custom_servers", "member_default_preset", "agent_default_preset", "is_admin"]
        extra_kwargs = {
            "allow_custom_servers": {
                "help_text": "Whether non-admin members may register custom MCP servers with the gateway."
            },
            "member_default_preset": {
                "help_text": "Baseline preset for members. Empty until an admin applies one from Team settings."
            },
            "agent_default_preset": {
                "help_text": "Baseline preset deriving default policies for tools an agent has no explicit row for."
            },
        }

    @extend_schema_field(serializers.BooleanField())
    def get_is_admin(self, obj: TeamMCPGatewayConfig) -> bool:
        return bool(self.context.get("is_admin"))


class GatewayConfigUpdateSerializer(serializers.Serializer):
    allow_custom_servers = serializers.BooleanField(
        required=False, help_text="Whether non-admin members may register custom MCP servers."
    )
    member_default_preset = serializers.ChoiceField(
        choices=POLICY_PRESET_CHOICES, required=False, allow_blank=True, help_text="Baseline preset for members."
    )
    agent_default_preset = serializers.ChoiceField(
        choices=POLICY_PRESET_CHOICES, required=False, allow_blank=True, help_text="Baseline preset for agents."
    )


class ApplyPresetSerializer(serializers.Serializer):
    audience = serializers.ChoiceField(
        choices=["members", "agents"], help_text="Which audience's baseline to overwrite."
    )
    preset = serializers.ChoiceField(choices=POLICY_PRESET_CHOICES, help_text="Preset to apply.")


class MCPServiceAccountSerializer(serializers.ModelSerializer):
    server_ids = serializers.SerializerMethodField(help_text="Gateway servers this agent has access to.")

    class Meta:
        model = MCPServiceAccount
        fields = [
            "id",
            "name",
            "description",
            "handle",
            "status",
            "token_mask",
            "server_ids",
            "last_active_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "name",
            "description",
            "handle",
            "status",
            "token_mask",
            "last_active_at",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "handle": {"help_text": "Stable identity handle the agent authenticates as, e.g. svc-docs-agent."},
            "status": {"help_text": "active, or paused (all access off)."},
            "token_mask": {"help_text": "Masked bearer token; the full token is only shown once."},
            "last_active_at": {"help_text": "When the agent last made a call through the gateway."},
        }

    @extend_schema_field(serializers.ListField(child=serializers.UUIDField()))
    def get_server_ids(self, obj: MCPServiceAccount) -> list[str]:
        return [str(access.gateway_server_id) for access in obj.server_access.all()]


class MCPServiceAccountWithTokenSerializer(MCPServiceAccountSerializer):
    token = serializers.SerializerMethodField(
        help_text="The full bearer token. Returned exactly once — on creation or rotation."
    )

    class Meta(MCPServiceAccountSerializer.Meta):
        fields = [*MCPServiceAccountSerializer.Meta.fields, "token"]

    @extend_schema_field(serializers.CharField())
    def get_token(self, obj: MCPServiceAccount) -> str:
        return self.context.get("token", "")


class MCPServiceAccountCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200, help_text="Agent display name, e.g. Docs Agent.")
    description = serializers.CharField(required=False, allow_blank=True, default="", help_text="What this agent does.")


class MCPServiceAccountUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = MCPServiceAccount
        fields = ["name", "description", "status"]
        extra_kwargs = {
            "name": {"required": False, "help_text": "Agent display name."},
            "description": {"required": False, "help_text": "What this agent does."},
            "status": {"required": False, "help_text": "active, or paused (all access off)."},
        }


class ServiceAccountAccessUpdateSerializer(serializers.Serializer):
    gateway_server_id = serializers.UUIDField(help_text="Gateway server to grant or revoke.")
    enabled = serializers.BooleanField(help_text="True grants access, false revokes it.")
    policies = ToolPolicyEntrySerializer(
        many=True,
        required=False,
        default=list,
        help_text="Optional agent-scope tool policies to set alongside the grant.",
    )


class MCPOrgRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = MCPOrgRule
        fields = [
            "id",
            "name",
            "description",
            "applies_to",
            "effect",
            "tool_pattern",
            "enabled",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
        extra_kwargs = {
            "name": {"help_text": "Short rule name shown wherever the rule locks a tool."},
            "description": {"required": False, "help_text": "Why this guardrail exists."},
            "applies_to": {"required": False, "help_text": "Audience the rule constrains."},
            "effect": {"required": False, "help_text": "State the rule forces on matching tools."},
            "tool_pattern": {
                "required": False,
                "help_text": "fnmatch pattern against tool names. Blank matches destructive tools heuristically.",
            },
            "enabled": {"required": False, "help_text": "Disabled rules are kept but not evaluated."},
        }


class AuditActorServiceAccountSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Service account id.")
    name = serializers.CharField(help_text="Agent display name.")
    handle = serializers.CharField(help_text="Agent identity handle.")


class MCPAuditEventSerializer(serializers.ModelSerializer):
    actor_user = UserBasicSerializer(read_only=True, allow_null=True, help_text="Member who made the call, if any.")
    actor_service_account = serializers.SerializerMethodField(
        help_text="Agent that made the call, if any. Null for member calls."
    )

    class Meta:
        model = MCPAuditEvent
        fields = [
            "id",
            "created_at",
            "server_name",
            "tool_name",
            "decision",
            "actor_user",
            "actor_service_account",
            "actor_label",
        ]
        read_only_fields = ["id", "created_at", "server_name", "tool_name", "decision", "actor_label"]
        extra_kwargs = {
            "server_name": {"help_text": "Gateway server name at call time (denormalized)."},
            "tool_name": {"help_text": "Tool that was called."},
            "decision": {"help_text": "How the gateway decided the call."},
            "actor_label": {"help_text": "Denormalized actor label (email or handle) that survives deletion."},
        }

    @extend_schema_field(AuditActorServiceAccountSerializer(allow_null=True))
    def get_actor_service_account(self, obj: MCPAuditEvent) -> dict[str, Any] | None:
        account = obj.actor_service_account
        if account is None:
            return None
        return {"id": account.id, "name": account.name, "handle": account.handle}


class AuditQuerySerializer(serializers.Serializer):
    quick_filter = serializers.ChoiceField(
        choices=AUDIT_QUICK_FILTER_CHOICES,
        required=False,
        default="all",
        help_text="all, agents (agent calls only), approvals (approved or pending), or blocked.",
    )
    actor_service_account_id = serializers.UUIDField(
        required=False, help_text="Only calls made by this service account."
    )


class AuditCountsSerializer(serializers.Serializer):
    all = serializers.IntegerField(help_text="Every audited tool call.")
    agents = serializers.IntegerField(help_text="Calls made by service accounts.")
    approvals = serializers.IntegerField(help_text="Calls that were approved or are awaiting approval.")
    blocked = serializers.IntegerField(help_text="Calls the gateway blocked.")


class GatewayMemberSummarySerializer(serializers.Serializer):
    """One team member's gateway posture (admin overview)."""

    user = UserBasicSerializer(help_text="The member.")
    is_org_admin = serializers.BooleanField(help_text="Whether the member is an organization admin or owner.")
    connected_server_ids = serializers.ListField(
        child=serializers.UUIDField(), help_text="Gateway servers the member has a personal connection to."
    )
    revoked_server_ids = serializers.ListField(
        child=serializers.UUIDField(), help_text="Gateway servers an admin turned off for this member."
    )


class MemberAccessUpdateSerializer(serializers.Serializer):
    gateway_server_id = serializers.UUIDField(help_text="Gateway server to toggle for the member.")
    enabled = serializers.BooleanField(help_text="False turns the server off for the member; true restores it.")


# ---------------------------------------------------------------------------
# Viewsets
# ---------------------------------------------------------------------------


class MCPGatewayServerViewSet(
    GatewayAdminMixin,
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """The team's gateway server registry. Registration happens through the
    install/share flows in views.py — this surface reads, tunes, and removes."""

    scope_object = "project"
    scope_object_read_actions = ["list", "retrieve", "tools"]
    scope_object_write_actions = ["update", "partial_update", "destroy", "policies"]
    serializer_class = MCPGatewayServerSerializer
    permission_classes = [IsAuthenticated]
    # Fail-closed manager raises if `.all()` runs at import; the real per-request
    # scoping happens in safely_get_queryset.
    queryset = MCPGatewayServer.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet[MCPGatewayServer]) -> QuerySet[MCPGatewayServer]:
        return (
            MCPGatewayServer.objects.for_team(self.team_id)
            .select_related("template", "created_by")
            .prefetch_related(
                Prefetch(
                    "installations",
                    queryset=MCPServerInstallation.objects.select_related("user").order_by("created_at"),
                ),
                Prefetch(
                    "agent_access",
                    queryset=MCPServiceAccountServerAccess.objects.unscoped().select_related(
                        "service_account", "granted_by"
                    ),
                ),
                "member_revocations",
            )
            .annotate(
                tool_count_annotated=Count(
                    "installations__tools__tool_name",
                    filter=Q(installations__tools__removed_at__isnull=True),
                    distinct=True,
                )
            )
            .order_by("name")
        )

    def get_serializer_class(self) -> type[serializers.BaseSerializer]:
        if self.action in ("update", "partial_update"):
            return MCPGatewayServerUpdateSerializer
        return MCPGatewayServerSerializer

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        self._require_project_admin()
        server = cast(MCPGatewayServer, serializer.save())
        report_user_action(
            cast(User, self.request.user),
            "mcp_gateway server updated",
            properties={
                "server_name": server.name,
                "is_team_enabled": server.is_team_enabled,
                "allow_personal_connections": server.allow_personal_connections,
            },
            team=self.team,
        )

    def perform_destroy(self, instance: MCPGatewayServer) -> None:
        self._require_project_admin()
        report_user_action(
            cast(User, self.request.user),
            "mcp_gateway server removed",
            properties={"server_name": instance.name, "server_url": instance.url},
            team=self.team,
        )
        # Installations survive (FK is SET_NULL): credentials aren't destroyed
        # by de-registering, they just drop back to pre-gateway behavior.
        instance.delete()

    def _resolve_scope(self, data: dict) -> tuple[str, User | None, MCPServiceAccount | None]:
        scope_type = data.get("scope_type", "team")
        if scope_type == "member":
            user_id = data.get("scope_user_id") or self.request.user.id
            membership_exists = OrganizationMembership.objects.filter(
                organization_id=self.team.organization_id, user_id=user_id
            ).exists()
            if not membership_exists:
                raise NotFound("User is not a member of this organization.")
            return "member", User.objects.get(id=user_id), None
        if scope_type == "agent":
            account_id = data.get("scope_service_account_id")
            if not account_id:
                raise serializers.ValidationError("scope_service_account_id is required for agent scope.")
            try:
                account = MCPServiceAccount.objects.for_team(self.team_id).get(id=account_id)
            except MCPServiceAccount.DoesNotExist:
                raise NotFound("Service account not found.")
            return "agent", None, account
        return "team", None, None

    def _require_scope_permission(self, scope_type: str, scope_user: User | None, write: bool = False) -> None:
        """Members may view team defaults and manage their own member scope;
        everything else is admin-only."""
        if self._is_project_admin():
            return
        if scope_type == "member" and scope_user is not None and scope_user.id == self.request.user.id:
            return
        if scope_type == "team" and not write:
            return
        raise PermissionDenied("Only project admins can manage this scope.")

    def _resolve_policies_for_scope(
        self,
        server: MCPGatewayServer,
        scope_type: str,
        scope_user: User | None,
        scope_account: MCPServiceAccount | None,
    ) -> list[dict[str, Any]]:
        if scope_type == "agent" and scope_account is not None:
            caller = GatewayCaller(kind="agent", service_account_id=str(scope_account.id))
        else:
            # Team scope resolves as a member with no scope rows of their own.
            caller = GatewayCaller(kind="member", user_id=scope_user.id if scope_user else None)
        context = PolicyContext(team_id=self.team_id, caller=caller, gateway_server=server)

        tools: list[tuple[str, str]] = []
        seen: set[str] = set()
        tool_rows = (
            MCPServerInstallationTool.objects.filter(installation__gateway_server=server, removed_at__isnull=True)
            .order_by("tool_name", "-last_seen_at")
            .values_list("tool_name", "description")
        )
        for tool_name, description in tool_rows:
            if tool_name in seen:
                continue
            seen.add(tool_name)
            tools.append((tool_name, description or ""))

        is_admin = self._is_project_admin()
        rows: list[dict[str, Any]] = []
        for tool_name, description in tools:
            resolved = context.resolve(tool_name, description)
            # Beyond rule locks, a member can't loosen an admin-imposed state —
            # unless the baseline is "Member decides".
            member_locked = (
                scope_type == "member"
                and not is_admin
                and resolved.state in ("needs_approval", "do_not_use")
                and (resolved.decided_by == "team" or (resolved.decided_by == "preset" and context.preset != "user"))
            )
            rows.append(
                {
                    "tool_name": tool_name,
                    "description": description,
                    "policy_state": resolved.state,
                    "team_state": resolved.team_state,
                    "locked": resolved.locked or member_locked,
                    "decided_by": resolved.decided_by,
                    "rule_name": resolved.rule_name,
                    "rule_description": resolved.rule_description,
                }
            )
        return rows

    @validated_request(
        query_serializer=GatewayPoliciesQuerySerializer,
        responses={200: OpenApiResponse(response=ResolvedToolPolicySerializer(many=True))},
    )
    @action(detail=True, methods=["get"], url_path="tools")
    def tools(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Tool catalog with the resolved policy for a scope."""
        server = self.get_object()
        scope_type, scope_user, scope_account = self._resolve_scope(request.validated_query_data)
        self._require_scope_permission(scope_type, scope_user)
        rows = self._resolve_policies_for_scope(server, scope_type, scope_user, scope_account)
        return Response({"count": len(rows), "next": None, "previous": None, "results": rows})

    @validated_request(
        request_serializer=GatewayPoliciesUpsertSerializer,
        responses={200: OpenApiResponse(response=ResolvedToolPolicySerializer(many=True))},
    )
    @action(detail=True, methods=["post"], url_path="policies")
    def policies(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Upsert per-tool states for a scope, returning the re-resolved catalog."""
        server = self.get_object()
        data = request.validated_data
        scope_type, scope_user, scope_account = self._resolve_scope(data)
        self._require_scope_permission(scope_type, scope_user, write=True)

        for entry in data["policies"]:
            MCPToolPolicy.objects.update_or_create(
                team_id=self.team_id,
                gateway_server=server,
                tool_name=entry["tool_name"],
                scope_type=scope_type,
                scope_user=scope_user,
                scope_service_account=scope_account,
                defaults={"state": entry["policy_state"]},
            )

        report_user_action(
            cast(User, request.user),
            "mcp_gateway tool policies updated",
            properties={
                "server_name": server.name,
                "scope_type": scope_type,
                "tool_count": len(data["policies"]),
            },
            team=self.team,
        )

        rows = self._resolve_policies_for_scope(server, scope_type, scope_user, scope_account)
        return Response({"count": len(rows), "next": None, "previous": None, "results": rows})


class MCPServiceAccountViewSet(GatewayAdminMixin, TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """Agent identities: creation mints a bearer token (shown once), access
    grants tie them to gateway servers. Reads are open to members so agent
    activity stays legible; every write is admin-only."""

    scope_object = "project"
    scope_object_read_actions = ["list", "retrieve"]
    scope_object_write_actions = ["create", "update", "partial_update", "destroy", "rotate_token", "access"]
    serializer_class = MCPServiceAccountSerializer
    permission_classes = [IsAuthenticated]
    queryset = MCPServiceAccount.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet[MCPServiceAccount]) -> QuerySet[MCPServiceAccount]:
        return MCPServiceAccount.objects.for_team(self.team_id).prefetch_related("server_access").order_by("name")

    def get_serializer_class(self) -> type[serializers.BaseSerializer]:
        if self.action in ("update", "partial_update"):
            return MCPServiceAccountUpdateSerializer
        return MCPServiceAccountSerializer

    def _unique_handle(self, name: str) -> str:
        slug = slugify(name) or "agent"
        base = f"svc-{slug}"
        existing = set(MCPServiceAccount.objects.for_team(self.team_id).values_list("handle", flat=True))
        handle = base
        suffix = 2
        while handle in existing:
            handle = f"{base}-{suffix}"
            suffix += 1
        return handle

    @validated_request(
        request_serializer=MCPServiceAccountCreateSerializer,
        responses={201: OpenApiResponse(response=MCPServiceAccountWithTokenSerializer)},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Create an agent and mint its gateway token (returned exactly once)."""
        self._require_project_admin()
        data = request.validated_data
        raw_token, token_hash, token_mask = generate_gateway_token()
        account = MCPServiceAccount.objects.create(
            team_id=self.team_id,
            name=data["name"],
            description=data.get("description", ""),
            handle=self._unique_handle(data["name"]),
            token_hash=token_hash,
            token_mask=token_mask,
            created_by=cast(User, request.user),
        )
        report_user_action(
            cast(User, request.user),
            "mcp_gateway agent created",
            properties={"handle": account.handle},
            team=self.team,
        )
        return Response(
            MCPServiceAccountWithTokenSerializer(account, context={"token": raw_token}).data,
            status=status.HTTP_201_CREATED,
        )

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        self._require_project_admin()
        account = cast(MCPServiceAccount, serializer.save())
        report_user_action(
            cast(User, self.request.user),
            "mcp_gateway agent updated",
            properties={"handle": account.handle, "status": account.status},
            team=self.team,
        )

    def perform_destroy(self, instance: MCPServiceAccount) -> None:
        self._require_project_admin()
        report_user_action(
            cast(User, self.request.user),
            "mcp_gateway agent deleted",
            properties={"handle": instance.handle},
            team=self.team,
        )
        instance.delete()

    @extend_schema(request=None, responses={200: OpenApiResponse(response=MCPServiceAccountWithTokenSerializer)})
    @action(detail=True, methods=["post"], url_path="rotate_token")
    def rotate_token(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Mint a new token; the previous one stops working immediately."""
        self._require_project_admin()
        account = self.get_object()
        raw_token, token_hash, token_mask = generate_gateway_token()
        account.token_hash = token_hash
        account.token_mask = token_mask
        account.save(update_fields=["token_hash", "token_mask", "updated_at"])
        report_user_action(
            cast(User, request.user),
            "mcp_gateway agent token rotated",
            properties={"handle": account.handle},
            team=self.team,
        )
        return Response(MCPServiceAccountWithTokenSerializer(account, context={"token": raw_token}).data)

    @validated_request(
        request_serializer=ServiceAccountAccessUpdateSerializer,
        responses={200: OpenApiResponse(response=MCPServiceAccountSerializer)},
    )
    @action(detail=True, methods=["post"], url_path="access")
    def access(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Grant or revoke this agent's access to one gateway server."""
        self._require_project_admin()
        account = self.get_object()
        data = request.validated_data
        try:
            server = MCPGatewayServer.objects.for_team(self.team_id).get(id=data["gateway_server_id"])
        except MCPGatewayServer.DoesNotExist:
            raise NotFound("Gateway server not found.")

        if data["enabled"]:
            MCPServiceAccountServerAccess.objects.get_or_create(
                service_account=account,
                gateway_server=server,
                defaults={"team_id": self.team_id, "granted_by": cast(User, request.user)},
            )
            for entry in data.get("policies") or []:
                MCPToolPolicy.objects.update_or_create(
                    team_id=self.team_id,
                    gateway_server=server,
                    tool_name=entry["tool_name"],
                    scope_type="agent",
                    scope_user=None,
                    scope_service_account=account,
                    defaults={"state": entry["policy_state"]},
                )
        else:
            MCPServiceAccountServerAccess.objects.filter(service_account=account, gateway_server=server).delete()
            MCPToolPolicy.objects.filter(
                gateway_server=server, scope_type="agent", scope_service_account=account
            ).delete()

        report_user_action(
            cast(User, request.user),
            "mcp_gateway agent access changed",
            properties={"handle": account.handle, "server_name": server.name, "enabled": data["enabled"]},
            team=self.team,
        )
        account = self.safely_get_queryset(self.get_queryset()).get(id=account.id)
        return Response(MCPServiceAccountSerializer(account).data)


class MCPOrgRuleViewSet(GatewayAdminMixin, TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """Team guardrails evaluated before any scope policy."""

    scope_object = "project"
    scope_object_read_actions = ["list", "retrieve"]
    scope_object_write_actions = ["create", "update", "partial_update", "destroy"]
    serializer_class = MCPOrgRuleSerializer
    permission_classes = [IsAuthenticated]
    queryset = MCPOrgRule.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet[MCPOrgRule]) -> QuerySet[MCPOrgRule]:
        return MCPOrgRule.objects.for_team(self.team_id).order_by("name")

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        self._require_project_admin()
        rule = cast(MCPOrgRule, serializer.save(team_id=self.team_id, created_by=cast(User, self.request.user)))
        report_user_action(
            cast(User, self.request.user),
            "mcp_gateway rule created",
            properties={"rule_name": rule.name, "effect": rule.effect},
            team=self.team,
        )

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        self._require_project_admin()
        rule = cast(MCPOrgRule, serializer.save())
        report_user_action(
            cast(User, self.request.user),
            "mcp_gateway rule updated",
            properties={"rule_name": rule.name, "enabled": rule.enabled},
            team=self.team,
        )

    def perform_destroy(self, instance: MCPOrgRule) -> None:
        self._require_project_admin()
        report_user_action(
            cast(User, self.request.user),
            "mcp_gateway rule deleted",
            properties={"rule_name": instance.name},
            team=self.team,
        )
        instance.delete()


class MCPAuditEventViewSet(
    GatewayAdminMixin,
    TeamAndOrgViewSetMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Read-only trail of proxied tool calls. Admin-only — it exposes what
    every member and agent has been doing."""

    scope_object = "project"
    scope_object_read_actions = ["list", "retrieve", "counts"]
    serializer_class = MCPAuditEventSerializer
    permission_classes = [IsAuthenticated]
    queryset = MCPAuditEvent.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet[MCPAuditEvent]) -> QuerySet[MCPAuditEvent]:
        return (
            MCPAuditEvent.objects.for_team(self.team_id)
            .select_related("actor_user", "actor_service_account")
            .order_by("-created_at")
        )

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        self._require_project_admin()
        return super().retrieve(request, *args, **kwargs)

    @validated_request(
        query_serializer=AuditQuerySerializer,
        responses={200: OpenApiResponse(response=MCPAuditEventSerializer(many=True))},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        self._require_project_admin()
        query = request.validated_query_data
        queryset = self.filter_queryset(self.get_queryset())

        quick_filter = query.get("quick_filter", "all")
        if quick_filter == "agents":
            queryset = queryset.filter(actor_service_account__isnull=False)
        elif quick_filter == "approvals":
            queryset = queryset.filter(decision__in=["approved", "pending"])
        elif quick_filter == "blocked":
            queryset = queryset.filter(decision="blocked")

        if account_id := query.get("actor_service_account_id"):
            queryset = queryset.filter(actor_service_account_id=account_id)

        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @extend_schema(responses={200: OpenApiResponse(response=AuditCountsSerializer)})
    @action(detail=False, methods=["get"], url_path="counts")
    def counts(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Totals backing the quick-filter chips."""
        self._require_project_admin()
        queryset = MCPAuditEvent.objects.for_team(self.team_id)
        return Response(
            {
                "all": queryset.count(),
                "agents": queryset.filter(actor_service_account__isnull=False).count(),
                "approvals": queryset.filter(decision__in=["approved", "pending"]).count(),
                "blocked": queryset.filter(decision="blocked").count(),
            }
        )


class MCPGatewayConfigViewSet(GatewayAdminMixin, TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Team-wide gateway settings. `list` returns the single config object."""

    scope_object = "project"
    scope_object_read_actions = ["list"]
    scope_object_write_actions = ["update_settings", "apply_preset"]
    permission_classes = [IsAuthenticated]
    pagination_class = None
    # Plain ViewSet: spectacular needs a fallback serializer for schema generation.
    serializer_class = TeamMCPGatewayConfigSerializer

    def _get_or_create_config(self) -> TeamMCPGatewayConfig:
        config, _ = TeamMCPGatewayConfig.objects.get_or_create(team_id=self.team_id)
        return config

    def _serialize_config(self, config: TeamMCPGatewayConfig) -> dict[str, Any]:
        return TeamMCPGatewayConfigSerializer(config, context={"is_admin": self._is_project_admin()}).data

    @extend_schema(responses={200: OpenApiResponse(response=TeamMCPGatewayConfigSerializer)})
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """The team's gateway settings, plus whether the caller can administer them."""
        return Response(self._serialize_config(self._get_or_create_config()))

    @validated_request(
        request_serializer=GatewayConfigUpdateSerializer,
        responses={200: OpenApiResponse(response=TeamMCPGatewayConfigSerializer)},
    )
    @action(detail=False, methods=["post"], url_path="update_settings")
    def update_settings(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Update team gateway settings (admin-only)."""
        self._require_project_admin()
        config = self._get_or_create_config()
        data = request.validated_data
        for field, value in data.items():
            setattr(config, field, value)
        config.save()
        if "allow_custom_servers" in data:
            report_user_action(
                request.user,
                "mcp_gateway custom servers toggled",
                properties={"allow_custom_servers": data["allow_custom_servers"]},
                team=self.team,
            )
        return Response(self._serialize_config(config))

    @validated_request(
        request_serializer=ApplyPresetSerializer,
        responses={200: OpenApiResponse(response=TeamMCPGatewayConfigSerializer)},
    )
    @action(detail=False, methods=["post"], url_path="apply_preset")
    def apply_preset(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Set the policy baseline for members or agents (admin-only)."""
        self._require_project_admin()
        data = request.validated_data
        audience = data["audience"]
        preset = data["preset"]
        config = self._get_or_create_config()
        if audience == "members":
            config.member_default_preset = preset
        else:
            config.agent_default_preset = preset
        config.save(update_fields=["member_default_preset", "agent_default_preset", "updated_at"])
        report_user_action(
            request.user,
            "mcp_gateway preset applied",
            properties={"audience": audience, "preset": preset},
            team=self.team,
        )
        return Response(self._serialize_config(config))


class MCPGatewayMemberViewSet(GatewayAdminMixin, TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Admin overview of each member's gateway posture, plus the per-member
    server kill switch."""

    scope_object = "project"
    scope_object_read_actions = ["list"]
    scope_object_write_actions = ["set_access"]
    permission_classes = [IsAuthenticated]
    pagination_class = None
    serializer_class = GatewayMemberSummarySerializer

    @extend_schema(responses={200: OpenApiResponse(response=GatewayMemberSummarySerializer(many=True))})
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        self._require_project_admin()
        memberships = (
            OrganizationMembership.objects.filter(organization_id=self.team.organization_id)
            .select_related("user")
            .order_by("user__first_name", "user__email")
        )

        connected: dict[int, list[str]] = {}
        for user_id, server_id in MCPServerInstallation.objects.filter(
            team_id=self.team_id, scope="personal", gateway_server__isnull=False
        ).values_list("user_id", "gateway_server_id"):
            connected.setdefault(user_id, []).append(str(server_id))

        revoked: dict[int, list[str]] = {}
        for user_id, server_id in MCPMemberServerRevocation.objects.for_team(self.team_id).values_list(
            "user_id", "gateway_server_id"
        ):
            revoked.setdefault(user_id, []).append(str(server_id))

        rows = []
        for membership in memberships:
            if membership.user is None:
                continue
            rows.append(
                {
                    "user": UserBasicSerializer(membership.user).data,
                    "is_org_admin": membership.level >= OrganizationMembership.Level.ADMIN,
                    "connected_server_ids": connected.get(membership.user_id, []),
                    "revoked_server_ids": revoked.get(membership.user_id, []),
                }
            )
        return Response(rows)

    @validated_request(
        request_serializer=MemberAccessUpdateSerializer,
        responses={204: None},
    )
    @action(detail=True, methods=["post"], url_path="set_access")
    def set_access(self, request: Request, pk: str | None = None, *args: Any, **kwargs: Any) -> Response:
        """Turn one gateway server off (or back on) for one member."""
        self._require_project_admin()
        try:
            user_id = int(pk or "")
        except ValueError:
            raise NotFound("Member not found.")
        if not OrganizationMembership.objects.filter(
            organization_id=self.team.organization_id, user_id=user_id
        ).exists():
            raise NotFound("Member not found.")

        data = request.validated_data
        try:
            server = MCPGatewayServer.objects.for_team(self.team_id).get(id=data["gateway_server_id"])
        except MCPGatewayServer.DoesNotExist:
            raise NotFound("Gateway server not found.")

        if data["enabled"]:
            MCPMemberServerRevocation.objects.filter(gateway_server=server, user_id=user_id).delete()
        else:
            MCPMemberServerRevocation.objects.get_or_create(
                gateway_server=server,
                user_id=user_id,
                defaults={"team_id": self.team_id, "revoked_by": cast(User, request.user)},
            )

        report_user_action(
            cast(User, request.user),
            "mcp_gateway member access changed",
            properties={"server_name": server.name, "enabled": data["enabled"]},
            team=self.team,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
