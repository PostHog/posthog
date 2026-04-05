from typing import Any

from django.db.models import Q, QuerySet

import structlog
import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from pydantic import ValidationError
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.permissions import AccessControlPermission
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin

from ..models.model_configuration import LLMModelConfiguration
from ..models.provider_keys import LLMProvider, LLMProviderKey
from ..models.taggers import Tagger, TaggerType, validate_tagger_config
from .metrics import llma_track_latency

logger = structlog.get_logger(__name__)


class TagDefinitionSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, help_text="Tag identifier")
    description = serializers.CharField(
        max_length=500, required=False, default="", allow_blank=True, help_text="Description to help the LLM classify"
    )


class TaggerConfigSerializer(serializers.Serializer):
    prompt = serializers.CharField(min_length=1, help_text="Prompt instructing the LLM how to tag generations")
    tags = TagDefinitionSerializer(many=True, help_text="Available tags the LLM can assign")
    min_tags = serializers.IntegerField(default=0, min_value=0, help_text="Minimum number of tags to apply")
    max_tags = serializers.IntegerField(
        required=False, allow_null=True, min_value=1, help_text="Maximum number of tags to apply (null = no limit)"
    )

    def validate_tags(self, value: list[dict]) -> list[dict]:
        if not value:
            raise serializers.ValidationError("At least one tag is required")
        names = [tag["name"] for tag in value]
        if len(names) != len(set(names)):
            raise serializers.ValidationError("Tag names must be unique")
        return value

    def validate(self, data: dict) -> dict:
        min_tags = data.get("min_tags", 0)
        max_tags = data.get("max_tags")
        if max_tags is not None and min_tags > max_tags:
            raise serializers.ValidationError({"min_tags": "min_tags cannot be greater than max_tags"})
        tags = data.get("tags", [])
        if max_tags is not None and max_tags > len(tags):
            raise serializers.ValidationError({"max_tags": "max_tags cannot exceed the number of defined tags"})
        return data


class ModelConfigurationSerializer(serializers.Serializer):
    """Nested serializer for model configuration."""

    provider = serializers.ChoiceField(choices=LLMProvider.choices)
    model = serializers.CharField(max_length=100)
    provider_key_id = serializers.UUIDField(required=False, allow_null=True)
    provider_key_name = serializers.SerializerMethodField(read_only=True)

    def get_provider_key_name(self, obj: LLMModelConfiguration) -> str | None:
        if obj.provider_key:
            return obj.provider_key.name
        return None

    def to_representation(self, instance: LLMModelConfiguration) -> dict[str, Any]:
        return {
            "provider": instance.provider,
            "model": instance.model,
            "provider_key_id": str(instance.provider_key_id) if instance.provider_key_id else None,
            "provider_key_name": instance.provider_key.name if instance.provider_key else None,
        }


class TaggerSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    model_configuration = ModelConfigurationSerializer(required=False, allow_null=True)
    tagger_config = serializers.JSONField(help_text="Tagger configuration (varies by tagger_type)")
    tagger_type = serializers.ChoiceField(choices=TaggerType.choices, default=TaggerType.LLM)

    class Meta:
        model = Tagger
        fields = [
            "id",
            "name",
            "description",
            "enabled",
            "tagger_type",
            "tagger_config",
            "conditions",
            "model_configuration",
            "created_at",
            "updated_at",
            "created_by",
            "deleted",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "created_by"]

    def validate(self, data: dict) -> dict:
        tagger_type = data.get("tagger_type", self.instance.tagger_type if self.instance else TaggerType.LLM)
        tagger_config = data.get("tagger_config")
        if tagger_config:
            try:
                data["tagger_config"] = validate_tagger_config(tagger_type, tagger_config)
            except (ValueError, ValidationError) as e:
                raise serializers.ValidationError({"tagger_config": str(e)})
        return data

    def _create_or_update_model_configuration(
        self, model_config_data: dict[str, Any] | None, team_id: int
    ) -> LLMModelConfiguration | None:
        if model_config_data is None:
            return None

        provider_key = None
        provider_key_id = model_config_data.get("provider_key_id")
        if provider_key_id:
            try:
                provider_key = LLMProviderKey.objects.get(id=provider_key_id, team_id=team_id)
            except LLMProviderKey.DoesNotExist:
                raise serializers.ValidationError(
                    {"model_configuration": {"provider_key_id": "Provider key not found"}}
                )

        model_config = LLMModelConfiguration(
            team_id=team_id,
            provider=model_config_data["provider"],
            model=model_config_data["model"],
            provider_key=provider_key,
        )
        model_config.full_clean()
        model_config.save()
        return model_config

    def create(self, validated_data: dict) -> Tagger:
        request = self.context["request"]
        team = self.context["get_team"]()
        validated_data["team"] = team
        validated_data["created_by"] = request.user

        model_config_data = validated_data.pop("model_configuration", None)
        if model_config_data:
            validated_data["model_configuration"] = self._create_or_update_model_configuration(
                model_config_data, team.id
            )

        return super().create(validated_data)

    def update(self, instance: Tagger, validated_data: dict) -> Tagger:
        model_config_data = validated_data.pop("model_configuration", None)

        if model_config_data is not None:
            if instance.model_configuration:
                old_config = instance.model_configuration
                instance.model_configuration = None
                old_config.delete()

            validated_data["model_configuration"] = self._create_or_update_model_configuration(
                model_config_data, instance.team_id
            )

        return super().update(instance, validated_data)


class TaggerFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(method="filter_search", help_text="Search in name or description")
    enabled = django_filters.BooleanFilter(help_text="Filter by enabled status")
    order_by = django_filters.OrderingFilter(
        fields=(
            ("created_at", "created_at"),
            ("updated_at", "updated_at"),
            ("name", "name"),
        ),
        field_labels={
            "created_at": "Created At",
            "updated_at": "Updated At",
            "name": "Name",
        },
    )

    class Meta:
        model = Tagger
        fields = {
            "id": ["in"],
            "enabled": ["exact"],
        }

    def filter_search(self, queryset: QuerySet, name: str, value: str) -> QuerySet:
        if value:
            return queryset.filter(Q(name__icontains=value) | Q(description__icontains=value))
        return queryset


class TaggerViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "tagger"
    permission_classes = [IsAuthenticated, AccessControlPermission]
    serializer_class = TaggerSerializer
    queryset = Tagger.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_class = TaggerFilter

    def safely_get_queryset(self, queryset: QuerySet[Tagger]) -> QuerySet[Tagger]:
        queryset = (
            queryset.filter(team_id=self.team_id)
            .select_related("created_by", "model_configuration", "model_configuration__provider_key")
            .order_by("-created_at")
        )
        if not self.action.endswith("update"):
            queryset = queryset.filter(deleted=False)

        return queryset

    def perform_create(self, serializer: TaggerSerializer) -> None:
        instance = serializer.save()

        conditions = instance.conditions or []
        tagger_config = instance.tagger_config or {}
        tag_count = len(tagger_config.get("tags", []))

        report_user_action(
            self.request.user,
            "llma tagger created",
            {
                "tagger_id": str(instance.id),
                "tagger_name": instance.name,
                "tag_count": tag_count,
                "has_description": bool(instance.description),
                "enabled": instance.enabled,
                "condition_count": len(conditions),
                "has_rollout_percentage": any(c.get("rollout_percentage", 100) < 100 for c in conditions),
                "prompt_length": len(tagger_config.get("prompt", "")),
            },
            team=self.team,
            request=self.request,
        )

    def perform_update(self, serializer: TaggerSerializer) -> None:
        is_deletion = serializer.validated_data.get("deleted") is True and not serializer.instance.deleted
        old_enabled_value = serializer.instance.enabled

        changed_fields: list[str] = []
        for field in ["name", "description", "enabled", "tagger_config", "conditions", "deleted"]:
            if field in serializer.validated_data:
                old_value = getattr(serializer.instance, field)
                new_value = serializer.validated_data[field]
                if old_value != new_value:
                    changed_fields.append(field)

        instance = serializer.save()

        if is_deletion:
            report_user_action(
                self.request.user,
                "llma tagger deleted",
                {
                    "tagger_id": str(instance.id),
                    "tagger_name": instance.name,
                    "was_enabled": old_enabled_value,
                },
                team=self.team,
                request=self.request,
            )
        elif changed_fields:
            report_user_action(
                self.request.user,
                "llma tagger updated",
                {
                    "tagger_id": str(instance.id),
                    "changed_fields": changed_fields,
                },
                team=self.team,
                request=self.request,
            )

    @llma_track_latency("llma_taggers_list")
    @monitor(feature=None, endpoint="llma_taggers_list", method="GET")
    def list(self, request: Request, *args, **kwargs) -> Response:
        return super().list(request, *args, **kwargs)

    @llma_track_latency("llma_taggers_retrieve")
    @monitor(feature=None, endpoint="llma_taggers_retrieve", method="GET")
    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        return super().retrieve(request, *args, **kwargs)

    @llma_track_latency("llma_taggers_create")
    @monitor(feature=None, endpoint="llma_taggers_create", method="POST")
    def create(self, request: Request, *args, **kwargs) -> Response:
        return super().create(request, *args, **kwargs)

    @llma_track_latency("llma_taggers_update")
    @monitor(feature=None, endpoint="llma_taggers_update", method="PUT")
    def update(self, request: Request, *args, **kwargs) -> Response:
        return super().update(request, *args, **kwargs)

    @llma_track_latency("llma_taggers_partial_update")
    @monitor(feature=None, endpoint="llma_taggers_partial_update", method="PATCH")
    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        return super().partial_update(request, *args, **kwargs)

    @action(detail=False, methods=["post"], url_path="test_hog")
    def test_hog(self, request: Request, **kwargs) -> Response:
        """Test Hog tagger code against sample events without saving."""
        import json

        from posthog.hogql import ast
        from posthog.hogql.query import execute_hogql_query

        from posthog.cdp.validation import compile_hog
        from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
        from posthog.models.team import Team
        from posthog.temporal.llm_analytics.message_utils import extract_text_from_messages
        from posthog.temporal.llm_analytics.run_evaluation import extract_event_io
        from posthog.temporal.llm_analytics.run_tagger import run_hog_tagger

        test_serializer = TestHogTaggerRequestSerializer(data=request.data)
        if not test_serializer.is_valid():
            return Response({"error": test_serializer.errors}, status=400)

        source = test_serializer.validated_data["source"]
        sample_count = test_serializer.validated_data["sample_count"]
        tags = test_serializer.validated_data.get("tags", [])
        valid_tag_names = {tag["name"] for tag in tags}

        try:
            bytecode = compile_hog(source, "destination")
        except serializers.ValidationError as e:
            return Response({"error": f"Compilation error: {e.detail}"}, status=400)
        except Exception:
            logger.exception("Unexpected error compiling Hog source")
            return Response({"error": "Compilation failed due to an unexpected error"}, status=400)

        team = Team.objects.get(id=self.team_id)

        where_exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value=["$ai_generation"]),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.Gt,
                left=ast.Field(chain=["timestamp"]),
                right=ast.ArithmeticOperation(
                    op=ast.ArithmeticOperationOp.Sub,
                    left=ast.Call(name="now", args=[]),
                    right=ast.Call(name="toIntervalDay", args=[ast.Constant(value=7)]),
                ),
            ),
        ]

        query = ast.SelectQuery(
            select=[
                ast.Field(chain=["uuid"]),
                ast.Field(chain=["event"]),
                ast.Field(chain=["properties"]),
                ast.Field(chain=["distinct_id"]),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(exprs=where_exprs),
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")],
            limit=ast.Constant(value=sample_count),
        )

        tag_queries(product=Product.LLM_ANALYTICS, feature=Feature.QUERY)
        response = execute_hogql_query(query=query, team=team, limit_context=None)

        if not response.results:
            return Response({"results": [], "message": "No recent AI events found in the last 7 days"})

        results = []
        for row in response.results:
            event_uuid = str(row[0])
            event_type = row[1]
            properties = row[2]
            distinct_id = row[3]

            if isinstance(properties, str):
                properties = json.loads(properties)

            event_data = {
                "uuid": event_uuid,
                "event": event_type,
                "properties": properties,
                "distinct_id": distinct_id or "",
            }

            result = run_hog_tagger(bytecode, event_data, valid_tag_names)

            input_raw, output_raw = extract_event_io(event_type, properties)
            input_preview = extract_text_from_messages(input_raw)[:200]
            output_preview = extract_text_from_messages(output_raw)[:200]

            results.append(
                {
                    "event_uuid": event_uuid,
                    "trace_id": properties.get("$ai_trace_id"),
                    "input_preview": input_preview,
                    "output_preview": output_preview,
                    "tags": result["tags"],
                    "reasoning": result["reasoning"],
                    "error": result["error"],
                }
            )

        return Response({"results": results})


class TestHogTaggerRequestSerializer(serializers.Serializer):
    source = serializers.CharField(required=True, min_length=1)  # type: ignore[assignment]
    sample_count = serializers.IntegerField(required=False, default=5, min_value=1, max_value=10)
    tags = serializers.ListField(child=serializers.DictField(), required=False, default=list)
