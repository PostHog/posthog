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

    def validate_url(self, value: str) -> str:
        if MCPServer.objects.filter(url=value).exists():
            raise serializers.ValidationError("A server with this URL already exists.")
        return value

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
        if not kind:
            return Response({"detail": "OAuth not supported for this server"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            oauth_config = OauthIntegration.oauth_config_for_kind(kind)
        except NotImplementedError:
            return Response({"detail": f"OAuth for {kind} is not configured"}, status=status.HTTP_400_BAD_REQUEST)

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
        if not kind:
            return Response({"detail": "OAuth not supported for this server"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            oauth_config = OauthIntegration.oauth_config_for_kind(kind)
        except NotImplementedError:
            return Response({"detail": f"OAuth for {kind} is not configured"}, status=status.HTTP_400_BAD_REQUEST)

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

        token_data = token_response.json()
        access_token = token_data.get("access_token")
        if not access_token:
            return Response({"detail": "No access token in response"}, status=status.HTTP_400_BAD_REQUEST)

        sensitive_config = {
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
