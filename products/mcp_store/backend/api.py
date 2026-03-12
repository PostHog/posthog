import time
import hashlib
import secrets
from datetime import timedelta
from typing import Any, cast
from urllib.parse import urlencode, urlparse

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.http import HttpResponse, StreamingHttpResponse
from django.utils import timezone

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import mixins, renderers, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.cloud_utils import is_dev_mode
from posthog.models import User
from posthog.models.integration import OauthIntegration
from posthog.rate_limit import (
    MCPOAuthBurstThrottle,
    MCPOAuthRedirectBurstThrottle,
    MCPOAuthRedirectSustainedThrottle,
    MCPOAuthSustainedThrottle,
    MCPProxyBurstThrottle,
    MCPProxySustainedThrottle,
)
from posthog.security.url_validation import is_url_allowed

from .models import RECOMMENDED_SERVERS, MCPOAuthState, MCPServer, MCPServerInstallation, SensitiveConfig
from .oauth import (
    OAuthAuthorizeURLError,
    OAuthTokenExchangeError,
    discover_oauth_metadata,
    exchange_dcr_token,
    exchange_known_provider_token,
    generate_pkce,
    register_dcr_client,
)
from .proxy import proxy_mcp_request, validate_installation_auth


class MCPProxyRenderer(renderers.BaseRenderer):
    """Accepts any content type so DRF content negotiation doesn't reject MCP requests."""

    media_type = "*/*"
    format = "mcp"

    def render(self, data, accepted_media_type=None, renderer_context=None):
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
    installation: MCPServerInstallation,
    server: MCPServer,
    token: str,
    install_source: str,
    twig_callback_url: str = "",
    pkce_verifier: str = "",
) -> MCPOAuthState:
    return MCPOAuthState.objects.create(
        token_hash=_hash_oauth_state_token(token),
        installation=installation,
        team=installation.team,
        server=server,
        install_source=install_source,
        twig_callback_url=twig_callback_url,
        pkce_verifier=pkce_verifier,
        expires_at=timezone.now() + timedelta(seconds=OAUTH_STATE_MAX_AGE_SECONDS),
    )


def _is_https(url: str) -> bool:
    """Check that a URL uses HTTPS. Returns True in dev mode to allow http://localhost."""
    if is_dev_mode():
        return True
    return urlparse(url).scheme == "https"


def _is_valid_twig_callback_url(url: str) -> bool:
    """Validate that a Twig callback URL is safe to redirect to (prevents open redirect)."""
    parsed = urlparse(url)
    if parsed.scheme in ("array", "twig", "posthog-code"):
        return True
    if is_dev_mode() and parsed.scheme == "http" and parsed.hostname == "localhost":
        return True
    return False


def _get_oauth_redirect_uri() -> str:
    """Get the global OAuth redirect URI."""
    return f"{settings.SITE_URL}/api/mcp_store/oauth_redirect/"


class RecommendedServerSerializer(serializers.Serializer):
    name = serializers.CharField()
    url = serializers.URLField()
    description = serializers.CharField()
    auth_type = serializers.ChoiceField(choices=["none", "api_key", "oauth"])
    oauth_provider_kind = serializers.CharField(required=False, default="")


@extend_schema(tags=["mcp_store"])
class MCPServerViewSet(TeamAndOrgViewSetMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    scope_object = "project"
    serializer_class = RecommendedServerSerializer
    permission_classes = [IsAuthenticated]

    @validated_request(
        responses={200: OpenApiResponse(response=RecommendedServerSerializer(many=True))},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = RecommendedServerSerializer(RECOMMENDED_SERVERS, many=True)
        return Response({"results": serializer.data})


class MCPServerInstallationSerializer(serializers.ModelSerializer):
    server_id = serializers.UUIDField(source="server.id", read_only=True, allow_null=True, default=None)
    needs_reauth = serializers.SerializerMethodField()
    pending_oauth = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    proxy_url = serializers.SerializerMethodField()

    class Meta:
        model = MCPServerInstallation
        fields = [
            "id",
            "server_id",
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
        read_only_fields = ["id", "server_id", "created_at", "updated_at"]

    def get_name(self, obj: MCPServerInstallation) -> str:
        if obj.display_name:
            return obj.display_name
        if obj.server:
            return obj.server.name
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
    oauth_provider_kind = serializers.CharField(required=False, allow_blank=True, default="")
    install_source = serializers.ChoiceField(
        choices=["posthog", "twig", "posthog-code"], required=False, default="posthog"
    )
    twig_callback_url = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_url(self, value: str) -> str:
        allowed, error = is_url_allowed(value)
        if not allowed:
            raise serializers.ValidationError(f"URL not allowed: {error}")
        return value

    def validate_twig_callback_url(self, value: str) -> str:
        if value and not _is_valid_twig_callback_url(value):
            raise serializers.ValidationError("Invalid callback URL")
        return value


class AuthorizeQuerySerializer(serializers.Serializer):
    server_id = serializers.UUIDField(required=True)
    install_source = serializers.ChoiceField(
        choices=["posthog", "twig", "posthog-code"], required=False, default="posthog"
    )
    twig_callback_url = serializers.CharField(required=False, allow_blank=True, default="")


class MCPServerInstallationUpdateSerializer(serializers.Serializer):
    display_name = serializers.CharField(required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    is_enabled = serializers.BooleanField(required=False)


class OAuthRedirectResponseSerializer(serializers.Serializer):
    redirect_url = serializers.URLField()


@extend_schema(tags=["mcp_store"])
class MCPServerInstallationViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "project"
    scope_object_read_actions = ["list", "retrieve", "authorize"]
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "patch",
        "destroy",
        "install_custom",
    ]
    queryset = MCPServerInstallation.objects.all()
    serializer_class = MCPServerInstallationSerializer
    lookup_field = "id"
    permission_classes = [IsAuthenticated]

    # Installations are user-scoped (safely_get_queryset filters by user), so
    # write actions like install/uninstall don't need project admin access.
    # Return project:read so AccessControlPermission requires "member" not "admin".
    _USER_SCOPED_ACTIONS = {"destroy", "partial_update", "install_custom"}

    def dangerously_get_required_scopes(self, request: Any, view: Any) -> list[str] | None:
        if self.action in self._USER_SCOPED_ACTIONS:
            return ["project:read"]
        return None

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return (
            queryset.filter(team_id=self.team_id, user=self.request.user)
            .select_related("server")
            .order_by("-created_at")
        )

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

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

    def _build_dcr_authorize_url(
        self,
        server: MCPServer,
        *,
        redirect_uri: str,
        state_token: str,
        code_challenge: str,
    ) -> str:
        query_params = {
            "client_id": server.oauth_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state_token,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        if scopes := server.oauth_metadata.get("scopes_supported"):
            query_params["scope"] = " ".join(scopes)

        auth_endpoint = server.oauth_metadata["authorization_endpoint"]
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
        oauth_provider_kind = data.get("oauth_provider_kind", "")

        install_source = data.get("install_source", "posthog")
        twig_callback_url = data.get("twig_callback_url", "")

        # If the auth type is OAuth, we need to authorize the user for the custom server
        if auth_type == "oauth":
            return self._authorize_for_custom(
                request,
                name=name,
                mcp_url=url,
                description=description,
                oauth_provider_kind=oauth_provider_kind,
                install_source=install_source,
                twig_callback_url=twig_callback_url,
            )
        elif auth_type == "api_key":
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

            result_serializer = MCPServerInstallationSerializer(installation, context=self.get_serializer_context())
            return Response(result_serializer.data, status=status.HTTP_201_CREATED)

        return Response(status=status.HTTP_400_BAD_REQUEST)

    # Initialize OAuth authorization for custom servers using Dynamic Client Registration (DCR):
    # Register a new client if needed, or reuse an existing registration.
    def _authorize_for_custom(
        self,
        request: Request,
        *,
        name: str,
        mcp_url: str,
        description: str,
        oauth_provider_kind: str = "",
        install_source: str = "posthog",
        twig_callback_url: str = "",
    ) -> HttpResponse:
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

        # Discover the OAuth server metadata using RFC 9728 Protected Resource Metadata.
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

        # Register or reuse an existing DCR client for this server.
        try:
            server = self._get_or_register_dcr_server(
                metadata=metadata,
                issuer_url=issuer_url,
                redirect_uri=redirect_uri,
                name=name,
                request=request,
                oauth_provider_kind=oauth_provider_kind,
            )
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

        # Store the server in the installation if it's not already set.
        # Typically happens on fresh install, but also covers relinking if the installations points to a different server.
        if installation.server != server:
            installation.server = server
            installation.save(update_fields=["server", "updated_at"])

        # Generate a PKCE challenge and state token for the OAuth flow.
        code_verifier, code_challenge = generate_pkce()
        token = secrets.token_urlsafe(32)
        _create_oauth_state(installation, server, token, install_source, twig_callback_url, pkce_verifier=code_verifier)

        try:
            authorize_url = self._build_dcr_authorize_url(
                server,
                redirect_uri=redirect_uri,
                state_token=token,
                code_challenge=code_challenge,
            )
        except OAuthAuthorizeURLError:
            if created:
                installation.delete()
            return Response({"detail": "Authorization endpoint must use HTTPS"}, status=status.HTTP_400_BAD_REQUEST)

        # Return the OAuth provider's authorization URL to redirect the user to.
        return Response({"redirect_url": authorize_url}, status=status.HTTP_200_OK)

    def _get_or_register_dcr_server(
        self,
        *,
        metadata: dict,
        issuer_url: str,
        redirect_uri: str,
        name: str,
        request: Request,
        oauth_provider_kind: str = "",
    ) -> MCPServer:
        existing_server = MCPServer.objects.filter(url=issuer_url).first()

        if existing_server and existing_server.oauth_client_id:
            cached_redirect_uri = existing_server.oauth_metadata.get("dcr_redirect_uri", "")
            if cached_redirect_uri == redirect_uri:
                return existing_server

            try:
                client_id = self._register_dcr_client_or_raise(existing_server.oauth_metadata, redirect_uri)
                new_metadata = dict(existing_server.oauth_metadata)
                new_metadata["dcr_redirect_uri"] = redirect_uri
                existing_server.oauth_metadata = new_metadata
                existing_server.oauth_client_id = client_id
                existing_server.save(update_fields=["oauth_metadata", "oauth_client_id", "updated_at"])
                return existing_server
            except DCRNotSupportedError:
                raise
            except DCRRegistrationFailedError:
                raise

        client_id = self._register_dcr_client_or_raise(metadata, redirect_uri)

        metadata_with_redirect = dict(metadata)
        metadata_with_redirect["dcr_redirect_uri"] = redirect_uri
        try:
            server, created = MCPServer.objects.get_or_create(
                url=issuer_url,
                defaults={
                    "name": name,
                    "oauth_provider_kind": oauth_provider_kind,
                    "oauth_metadata": metadata_with_redirect,
                    "oauth_client_id": client_id,
                    "created_by": request.user,
                },
            )
        except IntegrityError:
            existing = MCPServer.objects.filter(url=issuer_url).first()
            if not existing:
                raise DCRRegistrationFailedError
            server = existing
            created = False

        if not created and not server.oauth_client_id:
            server.oauth_metadata = metadata_with_redirect
            server.oauth_client_id = client_id
            server.save(update_fields=["oauth_metadata", "oauth_client_id", "updated_at"])

        return server

    @validated_request(query_serializer=AuthorizeQuerySerializer)
    @action(
        detail=False,
        methods=["get"],
        url_path="authorize",
        throttle_classes=[MCPOAuthBurstThrottle, MCPOAuthSustainedThrottle],
    )
    def authorize(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        server_id = request.validated_query_data["server_id"]
        install_source = request.validated_query_data.get("install_source", "posthog")
        twig_callback_url = request.validated_query_data.get("twig_callback_url", "")

        if twig_callback_url and not _is_valid_twig_callback_url(twig_callback_url):
            return Response({"detail": "Invalid callback URL"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            server = MCPServer.objects.get(id=server_id)
        except MCPServer.DoesNotExist:
            return Response({"detail": "Server not found"}, status=status.HTTP_404_NOT_FOUND)

        # Look up the user's installation to get the MCP URL for RFC 9728 discovery
        installation = MCPServerInstallation.objects.filter(
            team_id=self.team_id, user=cast(User, request.user), server=server
        ).first()

        if server.oauth_provider_kind:
            try:
                return self._authorize_known_provider(
                    server.oauth_provider_kind,
                    server,
                    install_source=install_source,
                    twig_callback_url=twig_callback_url,
                    installation=installation,
                )
            except NotImplementedError:
                pass

        mcp_url = installation.url if installation else server.url

        return self._authorize_dcr(
            server,
            mcp_url=mcp_url,
            installation=installation,
            install_source=install_source,
            twig_callback_url=twig_callback_url,
        )

    def _authorize_known_provider(
        self,
        kind: str,
        server: MCPServer,
        *,
        install_source: str = "posthog",
        twig_callback_url: str = "",
        installation: MCPServerInstallation | None = None,
    ) -> HttpResponse:
        oauth_config = OauthIntegration.oauth_config_for_kind(kind)
        redirect_uri = _get_oauth_redirect_uri()

        token = secrets.token_urlsafe(32)

        if installation:
            _create_oauth_state(installation, server, token, install_source, twig_callback_url)

        query_params = {
            "client_id": oauth_config.client_id,
            "scope": oauth_config.scope,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": token,
            **(oauth_config.additional_authorize_params or {}),
        }

        authorize_url = f"{oauth_config.authorize_url}?{urlencode(query_params)}"

        response = HttpResponse(status=302)
        response["Location"] = authorize_url
        return response

    def _authorize_dcr(
        self,
        server: MCPServer,
        *,
        mcp_url: str,
        installation: MCPServerInstallation | None = None,
        install_source: str = "posthog",
        twig_callback_url: str = "",
    ) -> HttpResponse:
        if blocked_response := self._validate_mcp_url_or_error_response(mcp_url):
            return blocked_response

        redirect_uri = _get_oauth_redirect_uri()

        cached_redirect_uri = server.oauth_metadata.get("dcr_redirect_uri", "") if server.oauth_metadata else ""
        needs_registration = (
            not server.oauth_metadata or not server.oauth_client_id or cached_redirect_uri != redirect_uri
        )

        if needs_registration:
            try:
                # Reuse the existing trusted metadata, if available, to avoid re-discovering the server, which potentially introduces a security risk
                if server.oauth_metadata:
                    metadata = dict(server.oauth_metadata)
                else:
                    metadata = discover_oauth_metadata(mcp_url)
                client_id = self._register_dcr_client_or_raise(metadata, redirect_uri, server_url=server.url)
            except DCRNotSupportedError:
                return Response(
                    {"detail": "This MCP server does not support automatic client registration (DCR)."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            except DCRRegistrationFailedError:
                return Response({"detail": "OAuth discovery/registration failed."}, status=status.HTTP_400_BAD_REQUEST)
            metadata["dcr_redirect_uri"] = redirect_uri
            server.oauth_metadata = metadata
            server.oauth_client_id = client_id
            server.save(update_fields=["oauth_metadata", "oauth_client_id", "updated_at"])

        code_verifier, code_challenge = generate_pkce()
        token = secrets.token_urlsafe(32)

        if installation:
            _create_oauth_state(
                installation, server, token, install_source, twig_callback_url, pkce_verifier=code_verifier
            )

        try:
            authorize_url = self._build_dcr_authorize_url(
                server,
                redirect_uri=redirect_uri,
                state_token=token,
                code_challenge=code_challenge,
            )
        except OAuthAuthorizeURLError:
            return Response({"detail": "Authorization endpoint must use HTTPS"}, status=status.HTTP_400_BAD_REQUEST)

        response = HttpResponse(status=302)
        response["Location"] = authorize_url
        return response


@extend_schema(tags=["mcp_store"])
class MCPOAuthRedirectViewSet(viewsets.ViewSet):
    """Team-agnostic public OAuth callback endpoint.

    OAuth providers redirect here after authorization. This endpoint
    validates the state token, exchanges the code for tokens, and
    redirects to the originating client (PostHog web or Twig).
    """

    permission_classes: list = []
    authentication_classes: list = []
    throttle_classes = [MCPOAuthRedirectBurstThrottle, MCPOAuthRedirectSustainedThrottle]

    def list(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        state_token = request.query_params.get("state")
        if not state_token:
            return Response({"detail": "Missing state parameter"}, status=status.HTTP_400_BAD_REQUEST)

        oauth_state = self._consume_oauth_state(state_token)
        if not oauth_state:
            logger.warning("OAuth redirect: invalid or expired state")
            return Response({"detail": "Invalid or expired OAuth state"}, status=status.HTTP_400_BAD_REQUEST)

        installation = oauth_state.installation
        install_source = oauth_state.install_source
        twig_callback_url = oauth_state.twig_callback_url
        server = oauth_state.server

        error = request.query_params.get("error")
        if error:
            logger.warning("OAuth redirect: provider error", error=error)
            error_msg = "cancelled" if error == "access_denied" else error
            return self._build_oauth_redirect(
                install_source, installation, error=error_msg, twig_callback_url=twig_callback_url
            )

        code = request.query_params.get("code")
        if not code:
            return self._build_oauth_redirect(
                install_source, installation, error="Missing authorization code", twig_callback_url=twig_callback_url
            )

        try:
            self._exchange_and_store_tokens(installation, server, code, oauth_state.pkce_verifier)
        except OAuthTokenExchangeError:
            return self._build_oauth_redirect(
                install_source,
                installation,
                error="token_exchange_failed",
                twig_callback_url=twig_callback_url,
            )

        return self._build_oauth_redirect(install_source, installation, twig_callback_url=twig_callback_url)

    @staticmethod
    def _consume_oauth_state(state_token: str) -> MCPOAuthState | None:
        token_hash = _hash_oauth_state_token(state_token)
        now = timezone.now()

        with transaction.atomic():
            oauth_state = (
                MCPOAuthState.objects.select_for_update()
                .select_related("installation", "server")
                .filter(token_hash=token_hash, consumed_at__isnull=True)
                .first()
            )
            if not oauth_state or oauth_state.expires_at <= now:
                return None

            oauth_state.consumed_at = now
            oauth_state.save(update_fields=["consumed_at", "updated_at"])
            return oauth_state

    @staticmethod
    def _exchange_and_store_tokens(
        installation: MCPServerInstallation, server: MCPServer, code: str, pkce_verifier: str
    ) -> None:
        has_pkce = bool(pkce_verifier)
        redirect_uri = _get_oauth_redirect_uri()
        if has_pkce:
            token_data = exchange_dcr_token(
                server=server,
                code=code,
                pkce_verifier=pkce_verifier,
                redirect_uri=redirect_uri,
                is_https=_is_https,
            )
        elif server.oauth_provider_kind:
            try:
                token_data = exchange_known_provider_token(
                    kind=server.oauth_provider_kind,
                    code=code,
                    redirect_uri=redirect_uri,
                )
            except NotImplementedError:
                token_data = exchange_dcr_token(
                    server=server,
                    code=code,
                    pkce_verifier=pkce_verifier,
                    redirect_uri=redirect_uri,
                    is_https=_is_https,
                )
        else:
            token_data = exchange_dcr_token(
                server=server,
                code=code,
                pkce_verifier=pkce_verifier,
                redirect_uri=redirect_uri,
                is_https=_is_https,
            )

        access_token = token_data.get("access_token")
        if not access_token:
            raise OAuthTokenExchangeError("No access token in response")

        sensitive_config: SensitiveConfig = {
            "access_token": access_token,
            "token_retrieved_at": int(time.time()),
        }
        if refresh_token := token_data.get("refresh_token"):
            sensitive_config["refresh_token"] = refresh_token
        if expires_in := token_data.get("expires_in"):
            sensitive_config["expires_in"] = expires_in

        installation.sensitive_configuration = sensitive_config
        installation.save(update_fields=["sensitive_configuration", "updated_at"])

    @staticmethod
    def _build_oauth_redirect(
        install_source: str,
        installation: MCPServerInstallation,
        *,
        team_id: int | None = None,
        error: str | None = None,
        twig_callback_url: str = "",
    ) -> HttpResponse:
        if install_source in ["twig", "posthog-code"] and twig_callback_url:
            params = {"status": "error", "error": error} if error else {"status": "success"}
            separator = "&" if "?" in twig_callback_url else "?"
            redirect_url = f"{twig_callback_url}{separator}{urlencode(params)}"
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
