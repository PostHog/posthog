from typing import cast

from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User
from products.editor.backend.models.codebase import Codebase
from products.editor.backend.services.codebase_sync import CodebaseSyncService


class CodebaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Codebase
        # fields = ["id", "team", "user"]
        read_only_fields = ["id", "user", "team"]

    def create(self, validated_data):
        validated_data["user"] = self.request.user
        validated_data["team_id"] = validated_data["team_id"]
        return super().create(validated_data)


class ArtifactSerializer(serializers.Serializer):
    id = serializers.CharField()
    type = serializers.ChoiceField(choices=["file", "dir"])
    parent_id = serializers.CharField(required=False)


class CodebaseSyncSerializer(serializers.Serializer):
    tree = serializers.ListField(child=ArtifactSerializer())
    branch = serializers.CharField(required=False)


class CodebaseSyncViewset(TeamAndOrgViewSetMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    def get_queryset(self):
        return Codebase.objects.filter(user=self.request.user)

    def get_serializer_class(self):
        if self.action == "sync":
            return CodebaseSyncSerializer
        return CodebaseSerializer

    @action(detail=True, methods=["PATCH"])
    def sync(self, request: Request, pk: str):
        codebase: Codebase = self.get_object()
        serializer = self.get_serializer(None, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        service = CodebaseSyncService(self.team, cast(User, request.user), codebase, validated_data.get("branch"))
        leaf_nodes_to_sync = service.sync(validated_data["tree"])
        return Response(leaf_nodes_to_sync)
