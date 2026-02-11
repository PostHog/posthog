from typing import Any

from django.db.models import QuerySet

import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer

from .models import MCPServer, MCPServerInstallation

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
        team_id = self.context["team_id"]
        if MCPServer.objects.filter(team_id=team_id, url=value).exists():
            raise serializers.ValidationError("A server with this URL already exists in this project.")
        return value

    def create(self, validated_data: dict[str, Any]) -> MCPServer:
        request = self.context["request"]
        team_id = self.context["team_id"]
        return MCPServer.objects.create(
            team_id=team_id,
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

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(team_id=self.team_id).order_by("-created_at")


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
        team_id = self.context["team_id"]
        if not MCPServer.objects.filter(id=value, team_id=team_id).exists():
            raise serializers.ValidationError("Server not found in this project.")
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
