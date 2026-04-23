import time
import hashlib
import secrets
from collections.abc import Mapping
from datetime import timedelta
from typing import Any, cast
from urllib.parse import urlencode, urlparse

from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet
from django.http import HttpResponse, StreamingHttpResponse
from django.utils import timezone

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import mixins, renderers, serializers, status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.cloud_utils import is_dev_mode
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.rate_limit import (
    MCPOAuthBurstThrottle,
    MCPOAuthRedirectBurstThrottle,
    MCPOAuthRedirectSustainedThrottle,
    MCPOAuthSustainedThrottle,
    MCPProxyBurstThrottle,
    MCPProxySustainedThrottle,
)
from posthog.security.url_validation import is_url_allowed

from ..models import MCPOAuthState, MCPServerInstallation, MCPServerInstallationTool, MCPServerTemplate, SensitiveConfig
from ..oauth import (
    OAuthAuthorizeURLError,
    OAuthTokenExchangeError,
    discover_oauth_metadata,
    exchange_oauth_token,
    generate_pkce,
    register_dcr_client,
)
from ..proxy import proxy_mcp_request, validate_installation_auth
from ..tasks import sync_installation_tools_task
from ..tools import ToolsFetchError, sync_installation_tools


class MCPProxyRenderer(renderers.BaseRenderer):
    """Accepts any content type so DRF content negotiation doesn't reject MCP requests."""

    media_type = "*/*"
    format = "mcp"

    def render(
        self,
        data: bytes,
        accepted_media_type: str | None = None,
        renderer_context: Mapping[str, Any] | None = None,
    ) -> bytes:
        return data


logger = structlog.get_logger(__name__)

OAUTH_STATE_MAX_AGE_SECONDS = 600  # 10 minutes


class DCRNotSupportedError(Exception):
    """Raised when an MCP server does not support Dynamic Client Registration."""


class DCRRegistrationFailedError(Exception):
    """Raised when Dynamic Client Registration fails."""


def _hash_oauth_state_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _create_oauth_state(
    request: Request,
    installation: MCPServerInstallation,
    token: str,
    install_source: str,
    posthog_code_callback_url: str = "",
    pkce_verifier: str = "",
    template: MCPServerTemplate | None = None,
) -> MCPOAuthState:
    # Ties the state to the initiating user. Only that user can consume it; prevents OAuth CSRF/session fixation.
    return MCPOAuthState.objects.create(
        token_hash=_hash_oauth_state_token(token),
        installation=installation,
        team=installation.team,
        template=template,
        install_source=install_source,
        posthog_code_callback_url=posthog_code_callback_url,
        pkce_verifier=pkce_verifier,
        expires_at=timezone.now() + timedelta(seconds=OAUTH_STATE_MAX_AGE_SECONDS),
        created_by=cast(User, request.user),
    )


def _is_https(url: str) -> bool:
    """Check that a URL uses HTTPS. Returns True in dev mode to allow http://localhost."""
    if is_dev_mode():
        return True
    return urlparse(url).scheme == "https"


def _is_valid_posthog_code_callback_url(url: str) -> bool:
    """Validate that a PostHog Code callback URL is safe to redirect to (prevents open redirect)."""
    parsed = urlparse(url)
    if parsed.scheme in ("array", "posthog-code"):
        return True
    if is_dev_mode() and parsed.scheme == "http" and parsed.hostname == "localhost":
        return True
    return False


def _get_oauth_redirect_uri() -> str:
    """Get the global OAuth redirect URI."""
    return f"{settings.SITE_URL}/api/mcp_store/oauth_redirect/"


class MCPServerTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = MCPServerTemplate
        fields = ["id", "name", "url", "description", "auth_type", "icon_key"]


@extend_schema(tags=["mcp_store"])
class MCPServerViewSet(TeamAndOrgViewSetMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """Lists curated MCP server templates that users can install with one click.

    Templates are seeded by PostHog operators and carry shared, encrypted
    OAuth client credentials. Inactive templates are hidden from the catalog.
    """

    scope_object = "project"
    serializer_class = MCPServerTemplateSerializer
    permission_classes = [IsAuthenticated]

    @validated_request(
        responses={200: OpenApiResponse(response=MCPServerTemplateSerializer(many=True))},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        queryset = MCPServerTemplate.objects.filter(is_active=True).order_by("name")
        serializer = MCPServerTemplateSerializer(queryset, many=True)
        return Response({"results": serializer.data})


class MCPServerInstallationSerializer(serializers.ModelSerializer):
    template_id = serializers.UUIDField(source="template.id", read_only=True, allow_null=True, default=None)
    needs_reauth = serializers.SerializerMethodField()
    pending_oauth = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    proxy_url = serializers.SerializerMethodField()

    class Meta:
        model = MCPServerInstallation
        fields = [
            "id",
            "template_id",
            "name",
            "display_name",
            "url",
            "description",
            "auth_type",
            "is_enabled",
            "needs_reauth",
            "pending_oauth",
            "proxy_url",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "template_id", "created_at", "updated_at"]

    def get_name(self, obj: MCPServerInstallation) -> str:
        if obj.display_name:
            return obj.display_name
        if obj.template:
            return obj.template.name
        return ""

    def get_needs_reauth(self, obj: MCPServerInstallation) -> bool:
        if obj.auth_type != "oauth":
            return False
        sensitive = obj.sensitive_configuration or {}
        return bool(sensitive.get("needs_reauth"))

    def get_pending_oauth(self, obj: MCPServerInstallation) -> bool:
        if obj.auth_type != "oauth":
            return False
        sensitive = obj.sensitive_configuration or {}
        return not sensitive.get("access_token")

    def get_proxy_url(self, obj: MCPServerInstallation) -> str:
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(
                f"/api/environments/{obj.team_id}/mcp_server_installations/{obj.id}/proxy/"
            )
        return ""


class InstallCustomSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    url = serializers.URLField(max_length=2048)
    auth_type = serializers.ChoiceField(choices=["api_key", "oauth"])
    api_key = serializers.CharField(required=False, allow_blank=True, default="")
    description = serializers.CharField(required=False, allow_blank=True, default="")
    # Optional user-supplied OAuth client credentials. When omitted and auth_type=oauth,
    # we fall back to per-user Dynamic Client Registration.
    client_id = serializers.CharField(required=False, allow_blank=True, default="")
    client_secret = serializers.CharField(required=False, allow_blank=True, default="")
    install_source = serializers.ChoiceField(choices=["posthog", "posthog-code"], required=False, default="posthog")
    posthog_code_callback_url = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_url(self, value: str) -> str:
        allowed, error = is_url_allowed(value)
        if not allowed:
            raise serializers.ValidationError(f"URL not allowed: {error}")
        return value

    def validate_posthog_code_callback_url(self, value: str) -> str:
        if value and not _is_valid_posthog_code_callback_url(value):
            raise serializers.ValidationError("Invalid callback URL")
        return value


class InstallTemplateSerializer(serializers.Serializer):
    template_id = serializers.UUIDField(required=True)
    api_key = serializers.CharField(required=False, allow_blank=True, default="")
    install_source = serializers.ChoiceField(choices=["posthog", "posthog-code"], required=False, default="posthog")
    posthog_code_callback_url = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_posthog_code_callback_url(self, value: str) -> str:
        if value and not _is_valid_posthog_code_callback_url(value):
            raise serializers.ValidationError("Invalid callback URL")
        return value


class AuthorizeQuerySerializer(serializers.Serializer):
    # Exactly one of template_id / installation_id must be provided.
    template_id = serializers.UUIDField(required=False)
    installation_id = serializers.UUIDField(required=False)
    install_source = serializers.ChoiceField(choices=["posthog", "posthog-code"], required=False, default="posthog")
    posthog_code_callback_url = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs: dict) -> dict:
        if bool(attrs.get("template_id")) == bool(attrs.get("installation_id")):
            raise serializers.ValidationError("Pass exactly one of template_id or installation_id")
        return attrs


class MCPServerInstallationUpdateSerializer(serializers.Serializer):
    display_name = serializers.CharField(required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    is_enabled = serializers.BooleanField(required=False)


class OAuthRedirectResponseSerializer(serializers.Serializer):
    redirect_url = serializers.URLField()


class MCPServerInstallationToolSerializer(serializers.ModelSerializer):
    class Meta:
        model = MCPServerInstallationTool
        fields = [
            "id",
            "tool_name",
            "display_name",
            "description",
            "input_schema",
            "approval_state",
            "last_seen_at",
            "removed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "tool_name",
            "display_name",
            "description",
            "input_schema",
            "last_seen_at",
            "removed_at",
            "created_at",
            "updated_at",
        ]


class ToolApprovalUpdateSerializer(serializers.Serializer):
    approval_state = serializers.ChoiceField(choices=["approved", "needs_approval", "do_not_use"])


@extend_schema(tags=["mcp_store"])
class MCPServerInstallationViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "project"
    scope_object_read_actions = ["list", "retrieve", "authorize", "list_tools"]
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "patch",
        "destroy",
        "install_custom",
        "install_template",
        "update_tool_approval",
        "refresh_tools",
    ]
    queryset = MCPServerInstallation.objects.all()
    serializer_class = MCPServerInstallationSerializer
    lookup_field = "id"
    permission_classes = [IsAuthenticated]

    # Installations are user-scoped (safely_get_queryset filters by user), so
    # write actions like install/uninstall don't need project admin access.
    # Return project:read so AccessControlPermission requires "member" not "admin".
    _USER_SCOPED_ACTIONS = {
        "destroy",
        "partial_update",
        "install_custom",
        "install_template",
        "update_tool_approval",
        "refresh_tools",
    }

    def dangerously_get_required_scopes(self, request: Any, view: Any) -> list[str] | None:
        if self.action in self._USER_SCOPED_ACTIONS:
            return ["project:read"]
        return None

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return (
            queryset.filter(team_id=self.team_id, user=self.request.user)
            .select_related("template")
            .order_by("-created_at")
        )

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def perform_destroy(self, instance: MCPServerInstallation) -> None:
        report_user_action(
            self.request.user,
            "mcp_store server uninstalled",
            properties={
                "server_name": _installation_name(instance),
                "server_url": instance.url,
                "auth_type": instance.auth_type,
            },
            team=self.team,
        )
        super().perform_destroy(instance)

    def _validate_mcp_url_or_error_response(self, mcp_url: str) -> Response | None:
        allowed, reason = is_url_allowed(mcp_url)
        if not allowed:
            logger.warning("SSRF blocked MCP server URL", url=mcp_url, reason=reason)
            return Response({"detail": "Server URL blocked by security policy"}, status=status.HTTP_400_BAD_REQUEST)
        return None

    def _register_dcr_client_or_raise(self, metadata: dict, redirect_uri: str, *, server_url: str = "") -> str:
        log_context = {"error": ""} if not server_url else {"server_url": server_url, "error": ""}
        try:
            return register_dcr_client(metadata, redirect_uri)
        except ValueError as e:
            log_context["error"] = str(e)
            logger.warning("DCR not supported", **log_context)
            raise DCRNotSupportedError from e
        except Exception as e:
            log_context["error"] = str(e)
            logger.exception("DCR registration failed", **log_context)
            raise DCRRegistrationFailedError from e

    def _build_authorize_url_from_metadata(
        self,
        *,
        metadata: dict,
        client_id: str,
        redirect_uri: str,
        state_token: str,
        code_challenge: str,
    ) -> str:
        query_params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state_token,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        if scopes := metadata.get("scopes_supported"):
            query_params["scope"] = " ".join(scopes)

        auth_endpoint = metadata.get("authorization_endpoint", "")
        if not auth_endpoint:
            raise OAuthAuthorizeURLError("Authorization endpoint missing from metadata")
        if not _is_https(auth_endpoint):
            raise OAuthAuthorizeURLError("Authorization endpoint must use HTTPS")

        return f"{auth_endpoint}?{urlencode(query_params)}"

    @validated_request(
        MCPServerInstallationUpdateSerializer,
        responses={200: OpenApiResponse(response=MCPServerInstallationSerializer)},
    )
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        installation = self.get_object()
        data = request.validated_data

        if "is_enabled" in data:
            report_user_action(
                request.user,
                "mcp_store server toggled",
                properties={
                    "server_name": _installation_name(installation),
                    "server_url": installation.url,
                    "auth_type": installation.auth_type,
                    "is_enabled": data["is_enabled"],
                },
                team=self.team,
            )

        for field, value in data.items():
            setattr(installation, field, value)
        installation.save()

        serializer = self.get_serializer(installation)
        return Response(serializer.data)

    @action(
        detail=True,
        methods=["post"],
        url_path="proxy",
        throttle_classes=[MCPProxyBurstThrottle, MCPProxySustainedThrottle],
        required_scopes=["project:read"],
        renderer_classes=[MCPProxyRenderer],
    )
    def proxy(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse | StreamingHttpResponse:
        installation = self.get_object()

        ok, error_response = validate_installation_auth(installation)
        if not ok and error_response is not None:
            return error_response

        return proxy_mcp_request(request, installation)

    @validated_request(
        InstallTemplateSerializer,
        responses={
            200: OpenApiResponse(response=OAuthRedirectResponseSerializer),
            201: OpenApiResponse(response=MCPServerInstallationSerializer),
        },
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="install_template",
        throttle_classes=[MCPOAuthBurstThrottle, MCPOAuthSustainedThrottle],
    )
    def install_template(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        data = request.validated_data
        template_id = data["template_id"]
        install_source = data.get("install_source", "posthog")
        posthog_code_callback_url = data.get("posthog_code_callback_url", "")

        try:
            template = MCPServerTemplate.objects.get(id=template_id, is_active=True)
        except MCPServerTemplate.DoesNotExist:
            return Response({"detail": "Template not found"}, status=status.HTTP_404_NOT_FOUND)

        installation, created = MCPServerInstallation.objects.get_or_create(
            team_id=self.team_id,
            user=request.user,
            url=template.url,
            defaults={
                "template": template,
                "display_name": template.name,
                "description": template.description,
                "auth_type": template.auth_type,
            },
        )
        # Re-link in case a previous install pointed elsewhere (e.g. post-migration reconnect).
        if installation.template_id != template.id:
            installation.template = template
            installation.display_name = installation.display_name or template.name
            installation.auth_type = template.auth_type
            installation.save(update_fields=["template", "display_name", "auth_type", "updated_at"])

        if template.auth_type == "api_key":
            api_key = data.get("api_key") or ""
            if not api_key:
                if created:
                    installation.delete()
                return Response({"detail": "api_key is required"}, status=status.HTTP_400_BAD_REQUEST)
            installation.sensitive_configuration = {"api_key": api_key}
            installation.save(update_fields=["sensitive_configuration", "updated_at"])

            # Tool sync runs in the background so a slow upstream can't block the install request.
            transaction.on_commit(lambda: sync_installation_tools_task.delay(str(installation.id)))

            report_user_action(
                request.user,
                "mcp_store server installed",
                properties={
                    "server_name": template.name,
                    "template_id": str(template.id),
                    "server_url": template.url,
                    "auth_type": "api_key",
                    "install_source": install_source,
                    "source": "template",
                },
                team=self.team,
            )
            result = MCPServerInstallationSerializer(installation, context=self.get_serializer_context())
            return Response(result.data, status=status.HTTP_201_CREATED)

        # OAuth template install — use the shared client credentials.
        credentials = template.oauth_credentials or {}
        client_id = credentials.get("client_id", "")
        if not client_id or not template.oauth_metadata:
            if created:
                installation.delete()
            return Response(
                {"detail": "Template is missing OAuth credentials"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        redirect_uri = _get_oauth_redirect_uri()
        code_verifier, code_challenge = generate_pkce()
        token = secrets.token_urlsafe(32)
        _create_oauth_state(
            request,
            installation,
            token,
            install_source,
            posthog_code_callback_url,
            pkce_verifier=code_verifier,
            template=template,
        )

        try:
            authorize_url = self._build_authorize_url_from_metadata(
                metadata=template.oauth_metadata,
                client_id=client_id,
                redirect_uri=redirect_uri,
                state_token=token,
                code_challenge=code_challenge,
            )
        except OAuthAuthorizeURLError as exc:
            logger.warning(
                "OAuth authorize URL build failed",
                template_id=str(template.id),
                error=str(exc),
            )
            if created:
                installation.delete()
            return Response({"detail": "Could not build OAuth authorize URL"}, status=status.HTTP_400_BAD_REQUEST)

        report_user_action(
            request.user,
            "mcp_store oauth started",
            properties={
                "server_name": template.name,
                "template_id": str(template.id),
                "install_source": install_source,
            },
            team=self.team,
        )
        return Response({"redirect_url": authorize_url}, status=status.HTTP_200_OK)

    @validated_request(
        InstallCustomSerializer,
        responses={
            200: OpenApiResponse(response=OAuthRedirectResponseSerializer),
            201: OpenApiResponse(response=MCPServerInstallationSerializer),
        },
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="install_custom",
        throttle_classes=[MCPOAuthBurstThrottle, MCPOAuthSustainedThrottle],
    )
    def install_custom(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        data = request.validated_data

        name = data["name"]
        url = data["url"]
        auth_type = data["auth_type"]
        api_key = data.get("api_key", "")
        description = data.get("description", "")
        user_client_id = (data.get("client_id") or "").strip()
        user_client_secret = (data.get("client_secret") or "").strip()

        install_source = data.get("install_source", "posthog")
        posthog_code_callback_url = data.get("posthog_code_callback_url", "")

        if auth_type == "oauth":
            return self._authorize_for_custom(
                request,
                name=name,
                mcp_url=url,
                description=description,
                user_client_id=user_client_id,
                user_client_secret=user_client_secret,
                install_source=install_source,
                posthog_code_callback_url=posthog_code_callback_url,
            )
        if auth_type == "api_key":
            sensitive_config: SensitiveConfig = {}
            if api_key:
                sensitive_config["api_key"] = api_key

            installation, created = MCPServerInstallation.objects.get_or_create(
                team_id=self.team_id,
                user=request.user,
                url=url,
                defaults={
                    "display_name": name,
                    "description": description,
                    "auth_type": "api_key",
                    "sensitive_configuration": sensitive_config,
                },
            )

            if not created:
                return Response({"detail": "This server URL is already installed."}, status=status.HTTP_400_BAD_REQUEST)

            transaction.on_commit(lambda: sync_installation_tools_task.delay(str(installation.id)))

            logger.info(
                "MCP server installed via API key",
                server_name=name,
                server_url=url,
                install_source=install_source,
                team_id=self.team_id,
            )
            report_user_action(
                request.user,
                "mcp_store server installed",
                properties={
                    "server_name": name,
                    "server_url": url,
                    "auth_type": "api_key",
                    "install_source": install_source,
                    "source": "custom",
                },
                team=self.team,
            )

            result_serializer = MCPServerInstallationSerializer(installation, context=self.get_serializer_context())
            return Response(result_serializer.data, status=status.HTTP_201_CREATED)

        return Response(status=status.HTTP_400_BAD_REQUEST)

    def _authorize_for_custom(
        self,
        request: Request,
        *,
        name: str,
        mcp_url: str,
        description: str,
        user_client_id: str = "",
        user_client_secret: str = "",
        install_source: str = "posthog",
        posthog_code_callback_url: str = "",
    ) -> HttpResponse:
        """Kick off an OAuth flow for a user-added MCP server.

        If the user supplied a ``client_id``, we trust their credentials and
        skip DCR. Otherwise we run a per-user Dynamic Client Registration so
        every installation has its own client_id — the upstream provider can
        then quarantine a single abusive user without breaking everyone else.
        """
        if blocked_response := self._validate_mcp_url_or_error_response(mcp_url):
            return blocked_response

        redirect_uri = _get_oauth_redirect_uri()

        installation, created = MCPServerInstallation.objects.get_or_create(
            team_id=self.team_id,
            user=request.user,
            url=mcp_url,
            defaults={
                "display_name": name,
                "description": description,
                "auth_type": "oauth",
            },
        )
        if not created and installation.auth_type != "oauth":
            installation.auth_type = "oauth"
            installation.save(update_fields=["auth_type", "updated_at"])

        try:
            metadata = discover_oauth_metadata(mcp_url)
        except Exception as e:
            logger.exception("OAuth discovery failed", server_url=mcp_url, error=str(e))
            if created:
                installation.delete()
            return Response({"detail": "OAuth discovery failed."}, status=status.HTTP_400_BAD_REQUEST)

        issuer_url = metadata.get("issuer", "")
        if not issuer_url:
            if created:
                installation.delete()
            return Response({"detail": "Could not determine OAuth issuer"}, status=status.HTTP_400_BAD_REQUEST)

        # Resolve per-installation client credentials: either user-supplied or fresh DCR.
        if user_client_id:
            client_id = user_client_id
            dcr_is_user_provided = True
        else:
            try:
                client_id = self._register_dcr_client_or_raise(metadata, redirect_uri, server_url=mcp_url)
            except DCRNotSupportedError:
                if created:
                    installation.delete()
                return Response(
                    {"detail": "This MCP server does not support Dynamic Client Registration (DCR)."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            except DCRRegistrationFailedError:
                if created:
                    installation.delete()
                return Response({"detail": "OAuth registration failed."}, status=status.HTTP_400_BAD_REQUEST)
            dcr_is_user_provided = False

        # Cache the (non-secret) discovery metadata and the per-user creds on
        # the installation itself so refresh + reconnect don't re-run discovery.
        installation.oauth_issuer_url = issuer_url
        installation.oauth_metadata = metadata

        sensitive = dict(installation.sensitive_configuration or {})
        if not created:
            # Re-install replaces the per-user DCR client, which invalidates any
            # tokens that were minted against the old client. Drop them and flag
            # the installation as needing reauth until the new callback completes,
            # so the UI + agent see pending_oauth=True in the interim.
            for stale_key in ("access_token", "refresh_token", "token_retrieved_at", "expires_in"):
                sensitive.pop(stale_key, None)
            sensitive["needs_reauth"] = True
        sensitive["dcr_client_id"] = client_id
        sensitive["dcr_is_user_provided"] = dcr_is_user_provided
        # Only persist a client_secret if we also trusted the user-supplied
        # client_id. A stray client_secret paired with a DCR-minted client_id
        # would never validate, so discard it.
        if dcr_is_user_provided and user_client_secret:
            sensitive["dcr_client_secret"] = user_client_secret
        else:
            sensitive.pop("dcr_client_secret", None)
        installation.sensitive_configuration = sensitive
        installation.save(
            update_fields=[
                "oauth_issuer_url",
                "oauth_metadata",
                "sensitive_configuration",
                "updated_at",
            ]
        )

        code_verifier, code_challenge = generate_pkce()
        token = secrets.token_urlsafe(32)
        _create_oauth_state(
            request,
            installation,
            token,
            install_source,
            posthog_code_callback_url,
            pkce_verifier=code_verifier,
            template=None,
        )

        try:
            authorize_url = self._build_authorize_url_from_metadata(
                metadata=metadata,
                client_id=client_id,
                redirect_uri=redirect_uri,
                state_token=token,
                code_challenge=code_challenge,
            )
        except OAuthAuthorizeURLError:
            if created:
                installation.delete()
            return Response({"detail": "Authorization endpoint must use HTTPS"}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"redirect_url": authorize_url}, status=status.HTTP_200_OK)

    @validated_request(query_serializer=AuthorizeQuerySerializer)
    @action(
        detail=False,
        methods=["get"],
        url_path="authorize",
        throttle_classes=[MCPOAuthBurstThrottle, MCPOAuthSustainedThrottle],
    )
    def authorize(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        """Start (or re-start) an OAuth flow.

        Pass ``template_id`` to (re)connect a catalog template, or
        ``installation_id`` to reconnect an existing custom install using its
        cached metadata and per-user DCR creds.
        """
        query = request.validated_query_data
        install_source = query.get("install_source", "posthog")
        posthog_code_callback_url = query.get("posthog_code_callback_url", "")

        if posthog_code_callback_url and not _is_valid_posthog_code_callback_url(posthog_code_callback_url):
            return Response({"detail": "Invalid callback URL"}, status=status.HTTP_400_BAD_REQUEST)

        if template_id := query.get("template_id"):
            return self._authorize_for_template(
                request,
                template_id=template_id,
                install_source=install_source,
                posthog_code_callback_url=posthog_code_callback_url,
            )

        installation_id = query.get("installation_id")
        return self._authorize_for_installation(
            request,
            installation_id=installation_id,
            install_source=install_source,
            posthog_code_callback_url=posthog_code_callback_url,
        )

    def _authorize_for_template(
        self,
        request: Request,
        *,
        template_id: Any,
        install_source: str,
        posthog_code_callback_url: str,
    ) -> HttpResponse:
        try:
            template = MCPServerTemplate.objects.get(id=template_id, is_active=True)
        except MCPServerTemplate.DoesNotExist:
            return Response({"detail": "Template not found"}, status=status.HTTP_404_NOT_FOUND)

        credentials = template.oauth_credentials or {}
        client_id = credentials.get("client_id", "")
        if not client_id or not template.oauth_metadata:
            return Response({"detail": "Template missing OAuth credentials"}, status=status.HTTP_400_BAD_REQUEST)

        installation, _ = MCPServerInstallation.objects.get_or_create(
            team_id=self.team_id,
            user=cast(User, request.user),
            url=template.url,
            defaults={
                "template": template,
                "display_name": template.name,
                "description": template.description,
                "auth_type": template.auth_type,
            },
        )
        if installation.template_id != template.id:
            installation.template = template
            installation.save(update_fields=["template", "updated_at"])

        redirect_uri = _get_oauth_redirect_uri()
        code_verifier, code_challenge = generate_pkce()
        token = secrets.token_urlsafe(32)
        _create_oauth_state(
            request,
            installation,
            token,
            install_source,
            posthog_code_callback_url,
            pkce_verifier=code_verifier,
            template=template,
        )
        try:
            authorize_url = self._build_authorize_url_from_metadata(
                metadata=template.oauth_metadata,
                client_id=client_id,
                redirect_uri=redirect_uri,
                state_token=token,
                code_challenge=code_challenge,
            )
        except OAuthAuthorizeURLError as exc:
            logger.warning(
                "OAuth authorize URL build failed",
                template_id=str(template.id),
                error=str(exc),
            )
            return Response({"detail": "Could not build OAuth authorize URL"}, status=status.HTTP_400_BAD_REQUEST)

        report_user_action(
            request.user,
            "mcp_store oauth started",
            properties={
                "server_name": template.name,
                "template_id": str(template.id),
                "install_source": install_source,
            },
            team=self.team,
        )

        response = HttpResponse(status=302)
        response["Location"] = authorize_url
        return response

    def _authorize_for_installation(
        self,
        request: Request,
        *,
        installation_id: Any,
        install_source: str,
        posthog_code_callback_url: str,
    ) -> HttpResponse:
        """Reconnect an existing installation — typically for a custom (non-template) OAuth install.

        Uses the per-installation cached OAuth metadata and `sensitive_configuration["dcr_client_id"]`
        rather than re-running discovery/DCR. If the installation belongs to a template,
        we redirect through the template path so shared client creds are used.
        """
        try:
            installation = MCPServerInstallation.objects.get(
                id=installation_id, team_id=self.team_id, user=request.user.id
            )
        except MCPServerInstallation.DoesNotExist:
            return Response({"detail": "Installation not found"}, status=status.HTTP_404_NOT_FOUND)

        if installation.template_id:
            return self._authorize_for_template(
                request,
                template_id=installation.template_id,
                install_source=install_source,
                posthog_code_callback_url=posthog_code_callback_url,
            )

        if blocked_response := self._validate_mcp_url_or_error_response(installation.url):
            return blocked_response

        metadata = installation.oauth_metadata or {}
        sensitive = installation.sensitive_configuration or {}
        client_id = sensitive.get("dcr_client_id", "")
        if not metadata or not client_id:
            return Response(
                {"detail": "Installation is missing OAuth state — reinstall the server"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        redirect_uri = _get_oauth_redirect_uri()
        code_verifier, code_challenge = generate_pkce()
        token = secrets.token_urlsafe(32)
        _create_oauth_state(
            request,
            installation,
            token,
            install_source,
            posthog_code_callback_url,
            pkce_verifier=code_verifier,
            template=None,
        )
        try:
            authorize_url = self._build_authorize_url_from_metadata(
                metadata=metadata,
                client_id=client_id,
                redirect_uri=redirect_uri,
                state_token=token,
                code_challenge=code_challenge,
            )
        except OAuthAuthorizeURLError:
            return Response({"detail": "Authorization endpoint must use HTTPS"}, status=status.HTTP_400_BAD_REQUEST)

        response = HttpResponse(status=302)
        response["Location"] = authorize_url
        return response

    @extend_schema(responses={200: OpenApiResponse(response=MCPServerInstallationToolSerializer(many=True))})
    @action(detail=True, methods=["get"], url_path="tools")
    def list_tools(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        installation = self.get_object()
        include_removed = request.query_params.get("include_removed") == "1"
        queryset = installation.tools.order_by("tool_name")
        if not include_removed:
            queryset = queryset.filter(removed_at__isnull=True)
        serializer = MCPServerInstallationToolSerializer(queryset, many=True)
        return Response({"results": serializer.data})

    @validated_request(
        ToolApprovalUpdateSerializer,
        responses={200: OpenApiResponse(response=MCPServerInstallationToolSerializer)},
    )
    @action(
        detail=True,
        methods=["patch"],
        url_path=r"tools/(?P<tool_name>[^/]+)",
    )
    def update_tool_approval(self, request: Request, tool_name: str, *args: Any, **kwargs: Any) -> Response:
        installation = self.get_object()
        try:
            tool = installation.tools.get(tool_name=tool_name)
        except MCPServerInstallationTool.DoesNotExist:
            return Response({"detail": "Tool not found"}, status=status.HTTP_404_NOT_FOUND)

        new_state = request.validated_data["approval_state"]
        if tool.approval_state != new_state:
            tool.approval_state = new_state
            tool.save(update_fields=["approval_state", "updated_at"])
            report_user_action(
                request.user,
                "mcp_store tool approval changed",
                properties={
                    "server_name": _installation_name(installation),
                    "server_url": installation.url,
                    "tool_name": tool.tool_name,
                    "approval_state": new_state,
                },
                team=self.team,
            )

        return Response(MCPServerInstallationToolSerializer(tool).data)

    @extend_schema(responses={200: OpenApiResponse(response=MCPServerInstallationToolSerializer(many=True))})
    @action(
        detail=True,
        methods=["post"],
        url_path="tools/refresh",
        throttle_classes=[MCPOAuthBurstThrottle, MCPOAuthSustainedThrottle],
    )
    def refresh_tools(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        installation = self.get_object()
        if not installation.is_enabled:
            return Response({"detail": "Installation is disabled"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            sync_installation_tools(installation)
        except ToolsFetchError as exc:
            logger.warning(
                "Tools refresh failed",
                installation_id=str(installation.id),
                error=str(exc),
            )
            return Response(
                {"detail": "Could not refresh tools from the upstream MCP server"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        queryset = installation.tools.filter(removed_at__isnull=True).order_by("tool_name")
        serializer = MCPServerInstallationToolSerializer(queryset, many=True)
        return Response({"results": serializer.data})


def _installation_name(installation: MCPServerInstallation) -> str:
    if installation.display_name:
        return installation.display_name
    if installation.template:
        return installation.template.name
    return installation.url


@extend_schema(tags=["mcp_store"])
class MCPOAuthRedirectViewSet(viewsets.ViewSet):
    """Team-agnostic public OAuth callback endpoint.

    OAuth providers redirect here after authorization. This endpoint
    validates the state token, exchanges the code for tokens, and
    redirects to the originating client (PostHog web or PostHog Code).
    """

    # Use SessionAuthentication; leave permission_classes empty for uniform 400s, not 401s
    permission_classes: list = []
    authentication_classes = [SessionAuthentication]
    throttle_classes = [MCPOAuthRedirectBurstThrottle, MCPOAuthRedirectSustainedThrottle]

    def list(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        state_token = request.query_params.get("state")
        if not state_token:
            return Response({"detail": "Missing state parameter"}, status=status.HTTP_400_BAD_REQUEST)

        oauth_state = self._consume_oauth_state(request, state_token)
        if not oauth_state:
            return Response({"detail": "Invalid or expired OAuth state"}, status=status.HTTP_400_BAD_REQUEST)

        installation = oauth_state.installation
        install_source = oauth_state.install_source
        posthog_code_callback_url = oauth_state.posthog_code_callback_url
        template = oauth_state.template
        server_name = template.name if template else _installation_name(installation)
        server_identifier = str(template.id) if template else str(installation.id)

        error = request.query_params.get("error")
        if error:
            logger.warning("OAuth redirect: provider error", error=error)
            error_msg = "cancelled" if error == "access_denied" else error
            report_user_action(
                installation.user,
                "mcp_store oauth failed",
                properties={
                    "server_name": server_name,
                    "template_id": str(template.id) if template else "",
                    "installation_id": str(installation.id),
                    "error": error_msg,
                    "install_source": install_source,
                },
                team=installation.team,
            )
            return self._build_oauth_redirect(
                install_source, installation, error=error_msg, posthog_code_callback_url=posthog_code_callback_url
            )

        code = request.query_params.get("code")
        if not code:
            logger.warning(
                "OAuth redirect: missing authorization code",
                server_url=installation.url,
                install_source=install_source,
            )
            return self._build_oauth_redirect(
                install_source,
                installation,
                error="Missing authorization code",
                posthog_code_callback_url=posthog_code_callback_url,
            )

        try:
            self._exchange_and_store_tokens(installation, code, oauth_state.pkce_verifier)
        except OAuthTokenExchangeError:
            logger.exception(
                "OAuth redirect: token exchange failed",
                server_url=installation.url,
                installation_id=str(installation.id),
            )
            report_user_action(
                installation.user,
                "mcp_store oauth failed",
                properties={
                    "server_name": server_name,
                    "template_id": str(template.id) if template else "",
                    "installation_id": server_identifier,
                    "error": "token_exchange_failed",
                    "install_source": install_source,
                },
                team=installation.team,
            )
            return self._build_oauth_redirect(
                install_source,
                installation,
                error="token_exchange_failed",
                posthog_code_callback_url=posthog_code_callback_url,
            )

        # Tool sync runs in the background so a slow upstream can't block the OAuth redirect.
        transaction.on_commit(lambda: sync_installation_tools_task.delay(str(installation.id)))

        logger.info(
            "MCP server installed via OAuth",
            server_name=server_name,
            server_url=installation.url,
            install_source=install_source,
            team_id=installation.team_id,
        )
        report_user_action(
            installation.user,
            "mcp_store server installed",
            properties={
                "server_name": server_name,
                "template_id": str(template.id) if template else "",
                "installation_id": str(installation.id),
                "server_url": installation.url,
                "auth_type": "oauth",
                "install_source": install_source,
                "source": "template" if template else "custom",
            },
            team=installation.team,
        )

        return self._build_oauth_redirect(
            install_source, installation, posthog_code_callback_url=posthog_code_callback_url
        )

    def _consume_oauth_state(self, request: Request, state_token: str) -> MCPOAuthState | None:
        # Only allow the user who created the state to redeem it. Prevents CSRF or session fixation.
        if not request.user or not request.user.is_authenticated:
            logger.warning("OAuth redirect: unauthenticated callback")
            return None

        token_hash = _hash_oauth_state_token(state_token)
        now = timezone.now()
        with transaction.atomic():
            # Lock only the oauth_state row. `template` is nullable, so the
            # select_related join is a LEFT OUTER JOIN — Postgres rejects
            # FOR UPDATE on the nullable side of an outer join, so scope the lock with `of=`.
            oauth_state = (
                MCPOAuthState.objects.select_for_update(of=("self",))
                .select_related("installation", "template")
                .filter(token_hash=token_hash, consumed_at__isnull=True, created_by=request.user)
                .first()
            )
            if not oauth_state or oauth_state.expires_at <= now:
                logger.warning("OAuth redirect: state missing, expired, or owned by a different user")
                return None

            oauth_state.consumed_at = now
            oauth_state.save(update_fields=["consumed_at", "updated_at"])
            return oauth_state

    @staticmethod
    def _exchange_and_store_tokens(
        installation: MCPServerInstallation,
        code: str,
        pkce_verifier: str,
    ) -> None:
        redirect_uri = _get_oauth_redirect_uri()
        token_data = exchange_oauth_token(
            installation=installation,
            code=code,
            pkce_verifier=pkce_verifier,
            redirect_uri=redirect_uri,
            is_https=_is_https,
        )

        access_token = token_data.get("access_token")
        if not access_token:
            raise OAuthTokenExchangeError("No access token in response")

        # Preserve non-token state (DCR creds, api_key leftovers, etc.); reset
        # needs_reauth on successful reconnect.
        sensitive: dict = dict(installation.sensitive_configuration or {})
        sensitive.pop("needs_reauth", None)
        sensitive["access_token"] = access_token
        sensitive["token_retrieved_at"] = int(time.time())
        if refresh_token := token_data.get("refresh_token"):
            sensitive["refresh_token"] = refresh_token
        if expires_in := token_data.get("expires_in"):
            sensitive["expires_in"] = expires_in

        installation.sensitive_configuration = sensitive
        installation.save(update_fields=["sensitive_configuration", "updated_at"])

    @staticmethod
    def _build_oauth_redirect(
        install_source: str,
        installation: MCPServerInstallation,
        *,
        team_id: int | None = None,
        error: str | None = None,
        posthog_code_callback_url: str = "",
    ) -> HttpResponse:
        if install_source == "posthog-code" and posthog_code_callback_url:
            params = {"status": "error", "error": error} if error else {"status": "success"}
            separator = "&" if "?" in posthog_code_callback_url else "?"
            redirect_url = f"{posthog_code_callback_url}{separator}{urlencode(params)}"
        elif error:
            fallback_team_id = installation.team_id if installation else team_id
            redirect_url = f"{settings.SITE_URL}/project/{fallback_team_id}/settings/mcp-servers?oauth_error=true"
        else:
            redirect_url = (
                f"{settings.SITE_URL}/project/{installation.team_id}/settings/mcp-servers?oauth_complete=true"
            )

        response = HttpResponse(status=302)
        response["Location"] = redirect_url
        return response
