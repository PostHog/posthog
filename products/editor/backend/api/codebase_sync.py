from typing import cast

from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.models import User
from products.editor.backend.models.codebase import Codebase
from products.editor.backend.services.codebase_sync import CodebaseSyncService
from products.editor.backend.tasks import embed_file


class CodebaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Codebase
        fields = "__all__"
        read_only_fields = ["id", "user", "team"]

    def create(self, validated_data):
        validated_data["user"] = self.context["request"].user
        validated_data["team"] = self.context["get_team"]()
        return super().create(validated_data)


class ArtifactSerializer(serializers.Serializer):
    id = serializers.CharField()
    type = serializers.ChoiceField(choices=["file", "dir"])
    parent_id = serializers.CharField(required=False)


class CodebaseSyncSerializer(serializers.Serializer):
    tree = serializers.ListField(child=ArtifactSerializer())
    branch = serializers.CharField(required=False)


class CodebaseArtifactSerializer(serializers.Serializer):
    id = serializers.CharField()
    type = serializers.ChoiceField(choices=["file", "dir"])
    parent_id = serializers.CharField(required=False)
    branch = serializers.CharField(required=False)
    path = serializers.CharField()
    content = serializers.CharField(max_length=4_000_000)  # Roughly 1 million tokens.


class CodebaseSyncViewset(TeamAndOrgViewSetMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    scope_object = "editor_artifacts"

    authentication_classes = [PersonalAPIKeyAuthentication, SessionAuthentication]

    def safely_get_queryset(self):
        return Codebase.objects.filter(user=self.request.user)

    def get_serializer_class(self):
        if self.action == "sync":
            return CodebaseSyncSerializer
        if self.action == "sync_artifact":
            return CodebaseArtifactSerializer
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

    @action(detail=True, methods=["POST"], url_path="artifact/sync")
    def sync_artifact(self, request: Request, pk: str):
        codebase: Codebase = self.get_object()
        serializer = self.get_serializer(None, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        embed_file.delay(
            self.team.id,
            cast(User, request.user).id,
            codebase.id,
            branch=validated_data.get("branch"),
            artifact_id=validated_data["id"],
            parent_artifact_id=validated_data.get("parent_id"),
            file_path=validated_data["path"],
            file_content=validated_data["content"],
        )

        return Response(status=status.HTTP_202_ACCEPTED)
