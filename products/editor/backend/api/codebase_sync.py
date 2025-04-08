from django.forms import ValidationError
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.schema import CachedCodebaseTreeQueryResponse, CodebaseTreeQuery
from products.editor.backend.models.catalog_tree import ArtifactNode
from products.editor.backend.models.codebase import Codebase
from products.editor.backend.queries.codebase_tree import CodebaseTreeQueryRunner


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

        query_runner = CodebaseTreeQueryRunner(
            query=CodebaseTreeQuery(
                userId=request.user.id,
                codebaseId=codebase.id,
                branch=validated_data.get("branch"),
            ),
            team=self.team,
        )
        response = query_runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        if not isinstance(response, CachedCodebaseTreeQueryResponse):
            raise ValidationError("Failed to load the tree.")

        # handle new codebase
        if not response.results:
            pass
        else:
            client_tree = ArtifactNode.build_tree(validated_data["tree"])
            server_tree = ArtifactNode.build_tree(server_node.model_dump() for server_node in response.results)

            added, deleted = ArtifactNode.compare(server_tree, client_tree)

            # Delete nodes from the current codebase state

        return query_runner

    # def _delete_nodes(self, team: Team, user: User):
    #     query = "INSERT INTO codebase_catalog (team_id, user_id, codebase_id, artifact_id, branch, parent_artifact_id, is_deleted) VALUES"
    #     args: dict[str, Any] = {}
    #     for i, (artifact_id, parent_artifact_id) in enumerate(nodes):
    #         args.update(
    #             {
    #                 f"team_id_{i}": self.team.id,
    #                 f"user_id_{i}": self.request.user.id,
    #                 f"codebase_id_{i}": codebase.id,
    #                 f"artifact_id_{i}": artifact_id,
    #                 f"branch_{i}": branch,
    #                 f"parent_artifact_id_{i}": parent_artifact_id,
    #                 f"is_deleted_{i}": True,
    #             }
    #         )
