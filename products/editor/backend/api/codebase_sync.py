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
    parent_id = serializers.CharField(required=False, default=None)


class CodebaseSyncSerializer(serializers.Serializer):
    tree = serializers.ListField(child=ArtifactSerializer())
    branch = serializers.CharField(required=False)


class CodebaseSyncResponseSerializer(serializers.Serializer):
    diverging_files = serializers.ListField(child=serializers.CharField())


class CodebaseArtifactSerializer(serializers.Serializer):
    id = serializers.CharField()
    type = serializers.ChoiceField(choices=["file", "dir"])
    path = serializers.CharField()
    content = serializers.CharField(max_length=4_000_000)  # Roughly 1 million tokens.


class CodebaseSyncViewset(TeamAndOrgViewSetMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    scope_object = "editor_artifacts"
    scope_object_read_actions = []
    scope_object_write_actions = ["sync", "upload_artifact"]

    queryset = Codebase.objects.all()

    authentication_classes = [PersonalAPIKeyAuthentication, SessionAuthentication]

    def safely_get_queryset(self, qs):
        return qs.filter(user=cast(User, self.request.user))

    def get_serializer_class(self):
        if self.action == "sync":
            return CodebaseSyncSerializer
        if self.action == "upload_artifact":
            return CodebaseArtifactSerializer
        return CodebaseSerializer

    @action(detail=True, methods=["PATCH"])
    def sync(self, request: Request, *args, **kwargs):
        codebase: Codebase = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        service = CodebaseSyncService(self.team, cast(User, request.user), codebase, validated_data.get("branch"))
        diverging_files = service.sync(validated_data["tree"])
        return Response(CodebaseSyncResponseSerializer({"diverging_files": diverging_files}).data)

    @action(detail=True, methods=["POST"])
    def upload_artifact(self, request: Request, *args, **kwargs):
        codebase: Codebase = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        embed_file.delay(
            self.team.id,
            cast(User, request.user).id,
            codebase.id,
            artifact_id=validated_data["id"],
            file_path=validated_data["path"],
            file_content=validated_data["content"],
        )

        return Response(status=status.HTTP_202_ACCEPTED)
