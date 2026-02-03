import json

from django.db import transaction

from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from products.posthog_ai.backend.models import AgentMemory

EMBEDDING_MODEL = "text-embedding-3-small-1536"


class AgentMemorySerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentMemory
        fields = ["id", "contents", "metadata", "user_id", "created_at", "updated_at"]
        read_only_fields = ["id", "user_id", "created_at", "updated_at"]

    def create(self, validated_data):
        validated_data["team"] = self.context["get_team"]()
        validated_data["user"] = self.context["request"].user
        with transaction.atomic():
            memory = super().create(validated_data)
            memory.embed(EMBEDDING_MODEL)
        return memory

    def update(self, instance, validated_data):
        with transaction.atomic():
            memory = super().update(instance, validated_data)
            memory.embed(EMBEDDING_MODEL)
        return memory


class AgentMemoryQuerySerializer(serializers.Serializer):
    query_text = serializers.CharField(help_text="The search query for finding relevant memories")
    metadata_filter = serializers.DictField(
        required=False,
        default=dict,
        help_text="Filter by metadata key-value pairs, e.g. {'type': 'preference'}",
    )
    user_only = serializers.BooleanField(
        default=True, help_text="Search only current user's memories, or all team memories"
    )
    limit = serializers.IntegerField(default=10, min_value=1, max_value=100, help_text="Maximum number of results")


class MemoryQueryResultSerializer(serializers.Serializer):
    memory_id = serializers.CharField()
    contents = serializers.CharField()
    metadata = serializers.DictField()
    distance = serializers.FloatField()


class AgentMemoryViewSet(TeamAndOrgViewSetMixin, ModelViewSet):
    scope_object = "conversation"
    serializer_class = AgentMemorySerializer
    queryset = AgentMemory.objects.all()

    def get_queryset(self):
        return AgentMemory.objects.filter(team=self.team)

    def perform_destroy(self, instance):
        # Soft delete in embeddings table, then hard delete in postgres
        # We mark as deleted in the embedding index first so it won't appear in semantic searches,
        # then remove the database record. The embed() call updates the embeddings table.
        instance.metadata = {**instance.metadata, "deleted": True}
        with transaction.atomic():
            instance.embed(EMBEDDING_MODEL)
            instance.delete()

    @action(detail=False, methods=["post"])
    def query(self, request, *args, **kwargs):
        """Semantic search of memories using embeddings."""
        serializer = AgentMemoryQuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        query_text = serializer.validated_data["query_text"]
        metadata_filter = serializer.validated_data.get("metadata_filter", {})
        user_only = serializer.validated_data.get("user_only", True)
        limit = serializer.validated_data.get("limit", 10)

        # Build metadata filter conditions
        metadata_conditions = []
        metadata_placeholders: dict[str, ast.Expr] = {}
        if metadata_filter:
            for i, (key, value) in enumerate(metadata_filter.items()):
                key_placeholder = f"meta_key_{i}"
                value_placeholder = f"meta_value_{i}"
                metadata_conditions.append(
                    f"JSONExtractString(metadata, {{{key_placeholder}}}) = {{{value_placeholder}}}"
                )
                metadata_placeholders[key_placeholder] = ast.Constant(value=key)
                metadata_placeholders[value_placeholder] = ast.Constant(value=str(value))

        metadata_filter_sql = " AND ".join(metadata_conditions) if metadata_conditions else "1=1"

        query = f"""
            SELECT
                document_id,
                content,
                metadata,
                cosineDistance(embedding, embedText({{query_text}}, {{model_name}})) as distance
            FROM (
                SELECT
                    document_id,
                    argMax(content, inserted_at) as content,
                    argMax(metadata, inserted_at) as metadata,
                    argMax(embedding, inserted_at) as embedding
                FROM document_embeddings
                WHERE model_name = {{model_name}}
                  AND product = 'posthog-ai'
                  AND document_type = 'memory'
                GROUP BY document_id, model_name, product, document_type, rendering
            )
            WHERE ({{skip_user_filter}} OR JSONExtractString(metadata, 'user_id') = {{user_id}})
              AND NOT JSONExtractBool(metadata, 'deleted')
              AND ({metadata_filter_sql})
            ORDER BY distance ASC
            LIMIT {{limit}}
        """

        user_id = str(request.user.id) if request.user else ""
        skip_user_filter = not user_only or not request.user

        result = execute_hogql_query(
            query_type="AgentMemoryQuery",
            query=query,
            team=self.team,
            placeholders={
                "query_text": ast.Constant(value=query_text),
                "model_name": ast.Constant(value=EMBEDDING_MODEL),
                "user_id": ast.Constant(value=user_id),
                "skip_user_filter": ast.Constant(value=skip_user_filter),
                "limit": ast.Constant(value=limit),
                **metadata_placeholders,
            },
        )

        memories = []
        for row in result.results or []:
            document_id, content, metadata_str, distance = row
            try:
                metadata_dict = json.loads(metadata_str) if isinstance(metadata_str, str) else metadata_str or {}
            except json.JSONDecodeError:
                metadata_dict = {}

            memories.append(
                {
                    "memory_id": document_id,
                    "contents": content,
                    "metadata": metadata_dict,
                    "distance": distance,
                }
            )

        return Response({"results": memories, "count": len(memories)})

    @action(detail=False, methods=["get"])
    def metadata_keys(self, request, *args, **kwargs):
        """List all unique metadata keys used across memories in the team."""
        memories = AgentMemory.objects.filter(team=self.team).values_list("metadata", flat=True)
        all_keys: set[str] = set()
        for metadata in memories:
            if isinstance(metadata, dict):
                all_keys.update(metadata.keys())

        return Response({"keys": sorted(all_keys)})
