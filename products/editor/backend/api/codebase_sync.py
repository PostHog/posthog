from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.schema import EditorSemanticSearchQuery
from products.editor.backend.queries.semantic_search import EditorSemanticSearchQueryRunner


class ArtifactSerializer(serializers.Serializer):
    id = serializers.CharField()
    type = serializers.ChoiceField(choices=["file", "dir"])
    parent_id = serializers.CharField(required=False)


class CodebaseSyncSerializer(serializers.Serializer):
    tree = serializers.ListField(child=ArtifactSerializer())


class CodebaseSyncViewset(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    @action(detail=False, methods=["POST"])
    def sync(self, request: Request):
        query_runner = EditorSemanticSearchQueryRunner(
            query=EditorSemanticSearchQuery(userId=request.user.id), team=self.team
        )
        return query_runner
