import secrets
from typing import Any
from urllib.parse import urlencode

from django.db.models import QuerySet
from django.http import HttpResponse

import requests
import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.integration import OauthIntegration

from .models import OAUTH_KIND_MAP, MCPServer, MCPServerInstallation
from .oauth import discover_oauth_metadata, generate_pkce, register_dcr_client

logger = structlog.get_logger(__name__)


class MCPServerSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = MCPServer
        fields = [
            "id",
            "name",
            "url",
            "description",
            "icon_url",
            "auth_type",
            "is_default",
            "created_at",
            "updated_at",
            "created_by",
        ]
        read_only_fields = ["id", "is_default", "created_at", "updated_at"]

    def create(self, validated_data: dict[str, Any]) -> MCPServer:
        request = self.context["request"]
        return MCPServer.objects.create(
            created_by=request.user,
            **validated_data,
        )


@extend_schema(tags=["mcp_store"])
class MCPServerViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "project"
    queryset = MCPServer.objects.all()
    serializer_class = MCPServerSerializer
    lookup_field = "id"
    permission_classes = [IsAuthenticated]

    def _should_skip_parents_filter(self) -> bool:
        return True

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.order_by("-created_at")

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        url = request.data.get("url", "")
        existing = MCPServer.objects.filter(url=url).first()
        if existing:
            serializer = self.get_serializer(existing)
            return Response(serializer.data, status=status.HTTP_200_OK)
        return super().create(request, *args, **kwargs)


class MCPServerInstallationSerializer(serializers.ModelSerializer):
    server = MCPServerSerializer(read_only=True)
    server_id = serializers.UUIDField(write_only=True)

    class Meta:
        model = MCPServerInstallation
        fields = [
            "id",
            "server",
            "server_id",
            "configuration",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_server_id(self, value: str) -> str:
        if not MCPServer.objects.filter(id=value).exists():
            raise serializers.ValidationError("Server not found.")
        team_id = self.context["team_id"]
        request = self.context["request"]
        if MCPServerInstallation.objects.filter(team_id=team_id, user=request.user, server_id=value).exists():
            raise serializers.ValidationError("This server is already installed.")
        return value

    def create(self, validated_data: dict[str, Any]) -> MCPServerInstallation:
        request = self.context["request"]
        team_id = self.context["team_id"]
        return MCPServerInstallation.objects.create(
            team_id=team_id,
            user=request.user,
            **validated_data,
        )


@extend_schema(tags=["mcp_store"])
class MCPServerInstallationViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "project"
    queryset = MCPServerInstallation.objects.all()
    serializer_class = MCPServerInstallationSerializer
    lookup_field = "id"
    permission_classes = [IsAuthenticated]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(team_id=self.team_id, user=self.request.user).order_by("-created_at")

    @action(detail=False, methods=["get"], url_path="authorize")
    def authorize(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        server_id = request.query_params.get("server_id")
        if not server_id:
            return Response({"detail": "server_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            server = MCPServer.objects.get(id=server_id)
        except MCPServer.DoesNotExist:
            return Response({"detail": "Server not found"}, status=status.HTTP_404_NOT_FOUND)

        kind = OAUTH_KIND_MAP.get(server.url)
        if kind:
            try:
                return self._authorize_known_provider(kind, server_id)
            except NotImplementedError:
                pass

        return self._authorize_dcr(server, server_id)

    def _authorize_known_provider(self, kind: str, server_id: str) -> HttpResponse:
        oauth_config = OauthIntegration.oauth_config_for_kind(kind)

        token = secrets.token_urlsafe(32)
        state_params = urlencode(
            {
                "next": "/mcp-store",
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
        response.set_cookie("ph_oauth_state", token, max_age=600, httponly=True, samesite="Lax")
        return response

    def _authorize_dcr(self, server: MCPServer, server_id: str) -> HttpResponse:
        from django.conf import settings

        redirect_uri = f"{settings.SITE_URL}/project/{self.team_id}/mcp-store"

        cached_redirect_uri = server.oauth_metadata.get("dcr_redirect_uri", "") if server.oauth_metadata else ""
        needs_registration = (
            not server.oauth_metadata or not server.oauth_client_id or cached_redirect_uri != redirect_uri
        )

        if needs_registration:
            try:
                metadata = discover_oauth_metadata(server.url)
                client_id = register_dcr_client(metadata, redirect_uri)
            except Exception as e:
                logger.exception("DCR registration failed", server_url=server.url, error=str(e))
                return Response(
                    {"detail": f"OAuth discovery/registration failed: {e}"}, status=status.HTTP_400_BAD_REQUEST
                )
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

        authorize_url = f"{server.oauth_metadata['authorization_endpoint']}?{urlencode(query_params)}"

        response = HttpResponse(status=302)
        response["Location"] = authorize_url
        response.set_cookie("ph_oauth_state", token, max_age=600, httponly=False, samesite="Lax")
        response.set_cookie("ph_pkce_verifier", code_verifier, max_age=600, httponly=True, samesite="Lax")
        return response

    @action(detail=False, methods=["post"], url_path="oauth_callback")
    def oauth_callback(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        code = request.data.get("code")
        server_id = request.data.get("server_id")

        if not code or not server_id:
            return Response({"detail": "code and server_id are required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            server = MCPServer.objects.get(id=server_id)
        except MCPServer.DoesNotExist:
            return Response({"detail": "Server not found"}, status=status.HTTP_404_NOT_FOUND)

        kind = OAUTH_KIND_MAP.get(server.url)
        if kind:
            try:
                token_data = self._exchange_known_provider_token(kind, code)
            except NotImplementedError:
                token_data = self._exchange_dcr_token(request, server, code)
        else:
            token_data = self._exchange_dcr_token(request, server, code)

        if isinstance(token_data, Response):
            return token_data

        access_token = token_data.get("access_token")
        if not access_token:
            return Response({"detail": "No access token in response"}, status=status.HTTP_400_BAD_REQUEST)

        sensitive_config: dict[str, Any] = {
            "access_token": access_token,
        }
        if refresh_token := token_data.get("refresh_token"):
            sensitive_config["refresh_token"] = refresh_token
        if expires_in := token_data.get("expires_in"):
            sensitive_config["expires_in"] = expires_in

        installation, created = MCPServerInstallation.objects.update_or_create(
            team_id=self.team_id,
            user=request.user,
            server=server,
            defaults={"sensitive_configuration": sensitive_config},
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
        )

        if token_response.status_code != 200:
            logger.error(
                "OAuth token exchange failed", status_code=token_response.status_code, body=token_response.text[:500]
            )
            return Response({"detail": "Failed to exchange authorization code"}, status=status.HTTP_400_BAD_REQUEST)

        return token_response.json()

    def _exchange_dcr_token(self, request: Request, server: MCPServer, code: str) -> dict | Response:
        from django.conf import settings

        code_verifier = request.COOKIES.get("ph_pkce_verifier")
        if not code_verifier:
            return Response({"detail": "Missing PKCE verifier"}, status=status.HTTP_400_BAD_REQUEST)

        if not server.oauth_metadata or not server.oauth_client_id:
            return Response({"detail": "Server missing OAuth configuration"}, status=status.HTTP_400_BAD_REQUEST)

        redirect_uri = f"{settings.SITE_URL}/project/{self.team_id}/mcp-store"
        token_response = requests.post(
            server.oauth_metadata["token_endpoint"],
            data={
                "client_id": server.oauth_client_id,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
        )

        if token_response.status_code != 200:
            logger.error(
                "DCR token exchange failed", status_code=token_response.status_code, body=token_response.text[:500]
            )
            return Response({"detail": "Failed to exchange authorization code"}, status=status.HTTP_400_BAD_REQUEST)

        return token_response.json()
