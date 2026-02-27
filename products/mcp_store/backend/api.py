import time
import secrets
from typing import Any, cast
from urllib.parse import urlencode, urlparse

from django.conf import settings
from django.db import IntegrityError
from django.db.models import QuerySet
from django.http import HttpResponse

import requests
import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.cloud_utils import is_dev_mode
from posthog.models import User
from posthog.models.integration import OauthIntegration
from posthog.rate_limit import MCPOAuthBurstThrottle, MCPOAuthSustainedThrottle
from posthog.security.url_validation import is_url_allowed

from .models import RECOMMENDED_SERVERS, MCPServer, MCPServerInstallation, SensitiveConfig
from .oauth import TIMEOUT, discover_oauth_metadata, generate_pkce, register_dcr_client

logger = structlog.get_logger(__name__)

_SECURE_COOKIES = settings.SITE_URL.startswith("https")


def _is_https(url: str) -> bool:
    """Check that a URL uses HTTPS. Returns True in dev mode to allow http://localhost."""
    if is_dev_mode():
        return True
    return urlparse(url).scheme == "https"


@extend_schema(tags=["mcp_store"])
class MCPServerViewSet(TeamAndOrgViewSetMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    scope_object = "project"
    serializer_class = serializers.Serializer
    permission_classes = [IsAuthenticated]

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response({"results": RECOMMENDED_SERVERS})


class MCPServerInstallationSerializer(serializers.ModelSerializer):
    server_id = serializers.UUIDField(source="server.id", read_only=True, allow_null=True, default=None)
    needs_reauth = serializers.SerializerMethodField()
    pending_oauth = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()

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
            "needs_reauth",
            "pending_oauth",
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


class InstallCustomSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    url = serializers.URLField(max_length=2048)
    auth_type = serializers.ChoiceField(choices=["api_key", "oauth"])
    api_key = serializers.CharField(required=False, allow_blank=True, default="")
    description = serializers.CharField(required=False, allow_blank=True, default="")
    oauth_provider_kind = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_url(self, value: str) -> str:
        allowed, error = is_url_allowed(value)
        if not allowed:
            raise serializers.ValidationError(f"URL not allowed: {error}")
        return value


class AuthorizeQuerySerializer(serializers.Serializer):
    server_id = serializers.UUIDField(required=True)


class OAuthCallbackRequestSerializer(serializers.Serializer):
    code = serializers.CharField(required=True)
    server_id = serializers.UUIDField(required=True)
    state_token = serializers.CharField(required=True)


class MCPServerInstallationUpdateSerializer(serializers.Serializer):
    display_name = serializers.CharField(required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)


class OAuthRedirectResponseSerializer(serializers.Serializer):
    redirect_url = serializers.URLField()


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
        "oauth_callback",
    ]
    queryset = MCPServerInstallation.objects.all()
    serializer_class = MCPServerInstallationSerializer
    lookup_field = "id"
    permission_classes = [IsAuthenticated]

    # Installations are user-scoped (safely_get_queryset filters by user), so
    # write actions like install/uninstall don't need project admin access.
    # Return project:read so AccessControlPermission requires "member" not "admin".
    _USER_SCOPED_ACTIONS = {"destroy", "install_custom", "oauth_callback"}

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

        # If the auth type is OAuth, we need to authorize the user for the custom server
        if auth_type == "oauth":
            return self._authorize_for_custom(
                request, name=name, mcp_url=url, description=description, oauth_provider_kind=oauth_provider_kind
            )
        sensitive_config: SensitiveConfig = {}
        if auth_type == "api_key" and api_key:
            sensitive_config["api_key"] = api_key

        installation, created = MCPServerInstallation.objects.get_or_create(
            team_id=self.team_id,
            user=request.user,
            url=url,
            defaults={
                "display_name": name,
                "description": description,
                "auth_type": auth_type,
                "sensitive_configuration": sensitive_config,
            },
        )

        if not created:
            return Response({"detail": "This server URL is already installed."}, status=status.HTTP_400_BAD_REQUEST)

        result_serializer = MCPServerInstallationSerializer(installation, context=self.get_serializer_context())
        return Response(result_serializer.data, status=status.HTTP_201_CREATED)

    def _authorize_for_custom(
        self, request: Request, *, name: str, mcp_url: str, description: str, oauth_provider_kind: str = ""
    ) -> HttpResponse:
        allowed, reason = is_url_allowed(mcp_url)
        if not allowed:
            logger.warning("SSRF blocked MCP server URL", url=mcp_url, reason=reason)
            return Response({"detail": "Server URL blocked by security policy"}, status=status.HTTP_400_BAD_REQUEST)

        redirect_uri = f"{settings.SITE_URL}/project/{self.team_id}/settings/mcp-servers"

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

        server = self._get_or_register_dcr_server(
            metadata=metadata,
            issuer_url=issuer_url,
            redirect_uri=redirect_uri,
            name=name,
            request=request,
            oauth_provider_kind=oauth_provider_kind,
        )
        if isinstance(server, Response):
            if created:
                installation.delete()
            return server

        if installation.server != server:
            installation.server = server
            installation.save(update_fields=["server", "updated_at"])

        code_verifier, code_challenge = generate_pkce()
        token = secrets.token_urlsafe(32)
        state = urlencode({"token": token, "server_id": str(server.id)})

        query_params = {
            "client_id": server.oauth_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        if scopes := server.oauth_metadata.get("scopes_supported"):
            query_params["scope"] = " ".join(scopes)

        auth_endpoint = server.oauth_metadata["authorization_endpoint"]
        if not _is_https(auth_endpoint):
            if created:
                installation.delete()
            return Response({"detail": "Authorization endpoint must use HTTPS"}, status=status.HTTP_400_BAD_REQUEST)

        authorize_url = f"{auth_endpoint}?{urlencode(query_params)}"

        response = Response({"redirect_url": authorize_url}, status=status.HTTP_200_OK)
        response.set_cookie("ph_oauth_state", token, max_age=600, httponly=True, samesite="Lax", secure=_SECURE_COOKIES)
        response.set_cookie(
            "ph_pkce_verifier", code_verifier, max_age=600, httponly=True, samesite="Lax", secure=_SECURE_COOKIES
        )
        return response

    def _get_or_register_dcr_server(
        self,
        *,
        metadata: dict,
        issuer_url: str,
        redirect_uri: str,
        name: str,
        request: Request,
        oauth_provider_kind: str = "",
    ) -> MCPServer | Response:
        existing_server = MCPServer.objects.filter(url=issuer_url).first()

        if existing_server and existing_server.oauth_client_id:
            cached_redirect_uri = existing_server.oauth_metadata.get("dcr_redirect_uri", "")
            if cached_redirect_uri == redirect_uri:
                return existing_server

            try:
                client_id = register_dcr_client(existing_server.oauth_metadata, redirect_uri)
                new_metadata = dict(existing_server.oauth_metadata)
                new_metadata["dcr_redirect_uri"] = redirect_uri
                existing_server.oauth_metadata = new_metadata
                existing_server.oauth_client_id = client_id
                existing_server.save(update_fields=["oauth_metadata", "oauth_client_id", "updated_at"])
                return existing_server
            except Exception as e:
                logger.exception("DCR registration failed", error=str(e))
                return Response({"detail": "OAuth registration failed."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            client_id = register_dcr_client(metadata, redirect_uri)
        except Exception as e:
            logger.exception("DCR registration failed", error=str(e))
            return Response({"detail": "OAuth registration failed."}, status=status.HTTP_400_BAD_REQUEST)

        metadata["dcr_redirect_uri"] = redirect_uri
        try:
            server, created = MCPServer.objects.get_or_create(
                url=issuer_url,
                defaults={
                    "name": name,
                    "oauth_provider_kind": oauth_provider_kind,
                    "oauth_metadata": metadata,
                    "oauth_client_id": client_id,
                    "created_by": request.user,
                },
            )
        except IntegrityError:
            existing = MCPServer.objects.filter(url=issuer_url).first()
            if not existing:
                return Response({"detail": "OAuth registration failed."}, status=status.HTTP_400_BAD_REQUEST)
            server = existing
            created = False

        if not created and not server.oauth_client_id:
            server.oauth_metadata = metadata
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

        try:
            server = MCPServer.objects.get(id=server_id)
        except MCPServer.DoesNotExist:
            return Response({"detail": "Server not found"}, status=status.HTTP_404_NOT_FOUND)

        if server.oauth_provider_kind:
            try:
                return self._authorize_known_provider(server.oauth_provider_kind, server_id)
            except NotImplementedError:
                pass

        # Look up the user's installation to get the MCP URL for RFC 9728 discovery
        installation = MCPServerInstallation.objects.filter(
            team_id=self.team_id, user=cast(User, request.user), server=server
        ).first()
        mcp_url = installation.url if installation else server.url

        return self._authorize_dcr(server, server_id, mcp_url=mcp_url)

    def _authorize_known_provider(self, kind: str, server_id: str) -> HttpResponse:
        oauth_config = OauthIntegration.oauth_config_for_kind(kind)

        token = secrets.token_urlsafe(32)
        state_params = urlencode(
            {
                "next": "/settings/mcp-servers",
                "token": token,
                "source": "mcp_store",
                "server_id": str(server_id),
            }
        )

        query_params = {
            "client_id": oauth_config.client_id,
            "scope": oauth_config.scope,
            "redirect_uri": OauthIntegration.redirect_uri(kind),
            "response_type": "code",
            "state": state_params,
            **(oauth_config.additional_authorize_params or {}),
        }

        authorize_url = f"{oauth_config.authorize_url}?{urlencode(query_params)}"

        response = HttpResponse(status=302)
        response["Location"] = authorize_url
        response.set_cookie("ph_oauth_state", token, max_age=600, httponly=True, samesite="Lax", secure=_SECURE_COOKIES)
        return response

    def _authorize_dcr(self, server: MCPServer, server_id: str, *, mcp_url: str) -> HttpResponse:
        allowed, reason = is_url_allowed(mcp_url)
        if not allowed:
            logger.warning("SSRF blocked MCP server URL", url=mcp_url, reason=reason)
            return Response({"detail": "Server URL blocked by security policy"}, status=status.HTTP_400_BAD_REQUEST)

        redirect_uri = f"{settings.SITE_URL}/project/{self.team_id}/settings/mcp-servers"

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
                client_id = register_dcr_client(metadata, redirect_uri)
            except Exception as e:
                logger.exception("DCR registration failed", server_url=server.url, error=str(e))
                return Response({"detail": "OAuth discovery/registration failed."}, status=status.HTTP_400_BAD_REQUEST)
            metadata["dcr_redirect_uri"] = redirect_uri
            server.oauth_metadata = metadata
            server.oauth_client_id = client_id
            server.save(update_fields=["oauth_metadata", "oauth_client_id", "updated_at"])

        code_verifier, code_challenge = generate_pkce()
        token = secrets.token_urlsafe(32)
        state = urlencode({"token": token, "server_id": str(server_id)})

        query_params = {
            "client_id": server.oauth_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        if scopes := server.oauth_metadata.get("scopes_supported"):
            query_params["scope"] = " ".join(scopes)

        auth_endpoint = server.oauth_metadata["authorization_endpoint"]
        if not _is_https(auth_endpoint):
            return Response({"detail": "Authorization endpoint must use HTTPS"}, status=status.HTTP_400_BAD_REQUEST)

        authorize_url = f"{auth_endpoint}?{urlencode(query_params)}"

        response = HttpResponse(status=302)
        response["Location"] = authorize_url
        response.set_cookie("ph_oauth_state", token, max_age=600, httponly=True, samesite="Lax", secure=_SECURE_COOKIES)
        response.set_cookie(
            "ph_pkce_verifier", code_verifier, max_age=600, httponly=True, samesite="Lax", secure=_SECURE_COOKIES
        )
        return response

    @validated_request(
        OAuthCallbackRequestSerializer,
        responses={
            200: OpenApiResponse(response=MCPServerInstallationSerializer),
            201: OpenApiResponse(response=MCPServerInstallationSerializer),
        },
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="oauth_callback",
        throttle_classes=[MCPOAuthBurstThrottle, MCPOAuthSustainedThrottle],
    )
    def oauth_callback(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        code = request.validated_data["code"]
        server_id = request.validated_data["server_id"]
        state_token = request.validated_data["state_token"]

        cookie_token = request.COOKIES.get("ph_oauth_state")
        if not cookie_token or not secrets.compare_digest(cookie_token, state_token):
            return Response({"detail": "Invalid OAuth state token"}, status=status.HTTP_403_FORBIDDEN)

        try:
            server = MCPServer.objects.get(id=server_id)
        except MCPServer.DoesNotExist:
            return Response({"detail": "Server not found"}, status=status.HTTP_404_NOT_FOUND)

        if server.oauth_provider_kind:
            try:
                token_data = self._exchange_known_provider_token(server.oauth_provider_kind, code)
            except NotImplementedError:
                token_data = self._exchange_dcr_token(request, server, code)
        else:
            token_data = self._exchange_dcr_token(request, server, code)

        if isinstance(token_data, Response):
            return token_data

        access_token = token_data.get("access_token")
        if not access_token:
            return Response({"detail": "No access token in response"}, status=status.HTTP_400_BAD_REQUEST)

        sensitive_config: SensitiveConfig = {
            "access_token": access_token,
            "token_retrieved_at": int(time.time()),
        }
        if refresh_token := token_data.get("refresh_token"):
            sensitive_config["refresh_token"] = refresh_token
        if expires_in := token_data.get("expires_in"):
            sensitive_config["expires_in"] = expires_in

        existing = MCPServerInstallation.objects.filter(
            team_id=self.team_id, user=cast(User, request.user), server=server
        ).first()

        install_url = existing.url if existing else server.url
        display_name = existing.display_name if existing else server.name
        description = existing.description if existing else server.description

        installation, created = MCPServerInstallation.objects.update_or_create(
            team_id=self.team_id,
            user=request.user,
            url=install_url,
            defaults={
                "server": server,
                "display_name": display_name or server.name,
                "description": description or server.description,
                "auth_type": "oauth",
                "sensitive_configuration": sensitive_config,
            },
        )

        serializer = self.get_serializer(installation)
        return Response(serializer.data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    def _exchange_known_provider_token(self, kind: str, code: str) -> dict | Response:
        oauth_config = OauthIntegration.oauth_config_for_kind(kind)

        token_response = requests.post(
            oauth_config.token_url,
            data={
                "client_id": oauth_config.client_id,
                "client_secret": oauth_config.client_secret,
                "code": code,
                "redirect_uri": OauthIntegration.redirect_uri(kind),
                "grant_type": "authorization_code",
            },
            timeout=TIMEOUT,
        )

        if token_response.status_code != 200:
            logger.error("OAuth token exchange failed", status_code=token_response.status_code)
            return Response({"detail": "Failed to exchange authorization code"}, status=status.HTTP_400_BAD_REQUEST)

        return token_response.json()

    def _exchange_dcr_token(self, request: Request, server: MCPServer, code: str) -> dict | Response:
        code_verifier = request.COOKIES.get("ph_pkce_verifier")
        if not code_verifier:
            return Response({"detail": "Missing PKCE verifier"}, status=status.HTTP_400_BAD_REQUEST)

        if not server.oauth_metadata or not server.oauth_client_id:
            return Response({"detail": "Server missing OAuth configuration"}, status=status.HTTP_400_BAD_REQUEST)

        redirect_uri = f"{settings.SITE_URL}/project/{self.team_id}/settings/mcp-servers"
        token_endpoint = server.oauth_metadata["token_endpoint"]

        allowed, reason = is_url_allowed(token_endpoint)
        if not allowed:
            logger.warning("SSRF blocked token endpoint", url=token_endpoint, reason=reason)
            return Response({"detail": "Token endpoint blocked by security policy"}, status=status.HTTP_400_BAD_REQUEST)

        if not _is_https(token_endpoint):
            return Response({"detail": "Token endpoint must use HTTPS"}, status=status.HTTP_400_BAD_REQUEST)

        token_response = requests.post(
            token_endpoint,
            data={
                "client_id": server.oauth_client_id,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
            timeout=TIMEOUT,
        )

        if token_response.status_code != 200:
            logger.error("DCR token exchange failed", status_code=token_response.status_code)
            return Response({"detail": "Failed to exchange authorization code"}, status=status.HTTP_400_BAD_REQUEST)

        return token_response.json()
