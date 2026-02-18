import json
from typing import Any, cast

from django.db.models import Q, QuerySet

import structlog
import django_filters
from django_filters.rest_framework import DjangoFilterBackend
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
from posthog.models import User
from posthog.permissions import AccessControlPermission
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.temporal.llm_analytics.message_utils import extract_text_from_messages
from posthog.temporal.llm_analytics.run_evaluation import run_hog_eval

from ..models.evaluation_configs import validate_evaluation_configs
from ..models.evaluations import Evaluation
from ..models.model_configuration import LLMModelConfiguration
from ..models.provider_keys import LLMProvider, LLMProviderKey
from .metrics import llma_track_latency

logger = structlog.get_logger(__name__)


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


class EvaluationSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    model_configuration = ModelConfigurationSerializer(required=False, allow_null=True)

    class Meta:
        model = Evaluation
        fields = [
            "id",
            "name",
            "description",
            "enabled",
            "evaluation_type",
            "evaluation_config",
            "output_type",
            "output_config",
            "conditions",
            "model_configuration",
            "created_at",
            "updated_at",
            "created_by",
            "deleted",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "created_by"]

    def validate(self, data):
        if "evaluation_config" in data and "output_config" in data:
            evaluation_type = data.get("evaluation_type")
            output_type = data.get("output_type")
            if evaluation_type and output_type:
                try:
                    data["evaluation_config"], data["output_config"] = validate_evaluation_configs(
                        evaluation_type, output_type, data["evaluation_config"], data["output_config"]
                    )
                except ValueError as e:
                    raise serializers.ValidationError({"config": str(e)})
        return data

    def _create_or_update_model_configuration(
        self, model_config_data: dict[str, Any] | None, team_id: int
    ) -> LLMModelConfiguration | None:
        """Create or update an LLMModelConfiguration from serializer data."""
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

    def create(self, validated_data):
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

    def update(self, instance, validated_data):
        model_config_data = validated_data.pop("model_configuration", None)

        if model_config_data is not None:
            # Delete old model configuration if it exists
            if instance.model_configuration:
                old_config = instance.model_configuration
                instance.model_configuration = None
                old_config.delete()

            validated_data["model_configuration"] = self._create_or_update_model_configuration(
                model_config_data, instance.team_id
            )

        return super().update(instance, validated_data)


class EvaluationFilter(django_filters.FilterSet):
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
        model = Evaluation
        fields = {
            "id": ["in"],
            "enabled": ["exact"],
        }

    def filter_search(self, queryset, name, value):
        if value:
            return queryset.filter(Q(name__icontains=value) | Q(description__icontains=value))
        return queryset


class EvaluationViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "evaluation"
    permission_classes = [IsAuthenticated, AccessControlPermission]
    serializer_class = EvaluationSerializer
    queryset = Evaluation.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_class = EvaluationFilter

    def safely_get_queryset(self, queryset: QuerySet[Evaluation]) -> QuerySet[Evaluation]:
        queryset = (
            queryset.filter(team_id=self.team_id)
            .select_related("created_by", "model_configuration", "model_configuration__provider_key")
            .order_by("-created_at")
        )
        if not self.action.endswith("update"):
            queryset = queryset.filter(deleted=False)

        return queryset

    @staticmethod
    def _get_config_length(instance) -> int:
        """Get the relevant config content length for tracking."""
        if instance.evaluation_config and isinstance(instance.evaluation_config, dict):
            if instance.evaluation_type == "hog":
                source = instance.evaluation_config.get("source", "")
                return len(source) if isinstance(source, str) else 0
            else:
                prompt = instance.evaluation_config.get("prompt", "")
                return len(prompt) if isinstance(prompt, str) else 0
        return 0

    def perform_create(self, serializer):
        instance = serializer.save()

        # Calculate properties for tracking
        conditions = instance.conditions or []
        condition_count = len(conditions)
        has_rollout_percentage = any(condition.get("rollout_percentage", 100) < 100 for condition in conditions)

        config_length = self._get_config_length(instance)

        # Track evaluation created
        report_user_action(
            cast(User, self.request.user),
            "llma evaluation created",
            {
                "evaluation_id": str(instance.id),
                "evaluation_name": instance.name,
                "evaluation_type": instance.evaluation_type,
                "output_type": instance.output_type,
                "has_description": bool(instance.description),
                "enabled": instance.enabled,
                "condition_count": condition_count,
                "has_rollout_percentage": has_rollout_percentage,
                "config_length": config_length,
            },
            self.team,
        )

    def perform_update(self, serializer):
        # Check if this is a deletion (soft delete)
        is_deletion = serializer.validated_data.get("deleted") is True and not serializer.instance.deleted

        # Capture old enabled state before save (for deletion tracking)
        old_enabled_value = serializer.instance.enabled

        # Track changes before update
        changed_fields: list[str] = []
        enabled_changed = False
        enabled_new_value = None
        condition_count_changed = False
        condition_count_new = 0
        config_content_changed = False

        for field in [
            "name",
            "description",
            "enabled",
            "evaluation_type",
            "output_type",
            "evaluation_config",
            "output_config",
            "conditions",
            "deleted",
        ]:
            if field in serializer.validated_data:
                old_value = getattr(serializer.instance, field)
                new_value = serializer.validated_data[field]
                if old_value != new_value:
                    changed_fields.append(field)

                    if field == "enabled":
                        enabled_changed = True
                        enabled_new_value = new_value
                    elif field == "conditions":
                        condition_count_changed = True
                        condition_count_new = len(new_value) if new_value else 0
                    elif field == "evaluation_config":
                        eval_type = serializer.validated_data.get(
                            "evaluation_type", serializer.instance.evaluation_type
                        )
                        config_key = "source" if eval_type == "hog" else "prompt"
                        old_content = old_value.get(config_key, "") if isinstance(old_value, dict) else ""
                        new_content = new_value.get(config_key, "") if isinstance(new_value, dict) else ""
                        if old_content != new_content:
                            config_content_changed = True

        instance = serializer.save()

        # Track appropriate event
        if is_deletion:
            report_user_action(
                cast(User, self.request.user),
                "llma evaluation deleted",
                {
                    "evaluation_id": str(instance.id),
                    "evaluation_name": instance.name,
                    "was_enabled": old_enabled_value,
                },
                self.team,
            )
        elif changed_fields:
            event_properties: dict[str, Any] = {
                "evaluation_id": str(instance.id),
                "changed_fields": changed_fields,
            }

            if enabled_changed:
                event_properties["enabled_changed"] = True
                event_properties["enabled_new_value"] = enabled_new_value
            if condition_count_changed:
                event_properties["condition_count_changed"] = True
                event_properties["condition_count_new"] = condition_count_new
            if config_content_changed:
                event_properties["config_content_changed"] = True

            report_user_action(
                cast(User, self.request.user),
                "llma evaluation updated",
                event_properties,
                self.team,
            )

    @llma_track_latency("llma_evaluations_list")
    @monitor(feature=None, endpoint="llma_evaluations_list", method="GET")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @llma_track_latency("llma_evaluations_retrieve")
    @monitor(feature=None, endpoint="llma_evaluations_retrieve", method="GET")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @llma_track_latency("llma_evaluations_create")
    @monitor(feature=None, endpoint="llma_evaluations_create", method="POST")
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @llma_track_latency("llma_evaluations_update")
    @monitor(feature=None, endpoint="llma_evaluations_update", method="PUT")
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @llma_track_latency("llma_evaluations_partial_update")
    @monitor(feature=None, endpoint="llma_evaluations_partial_update", method="PATCH")
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @action(detail=False, methods=["post"], url_path="test_hog")
    def test_hog(self, request: Request, **kwargs) -> Response:
        """Test Hog evaluation code against sample events without saving."""
        serializer = TestHogRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)

        source = serializer.validated_data["source"]
        sample_count = serializer.validated_data["sample_count"]
        conditions = serializer.validated_data.get("conditions", [])

        from posthog.hogql import ast
        from posthog.hogql.property import property_to_expr
        from posthog.hogql.query import execute_hogql_query

        from posthog.cdp.validation import compile_hog
        from posthog.models.team import Team

        try:
            bytecode = compile_hog(source, "destination")
        except Exception as e:
            return Response({"error": f"Compilation error: {e}"}, status=400)

        team = Team.objects.get(id=self.team_id)

        # Build WHERE clause from trigger conditions (OR between condition sets, AND within each)
        where_exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value=["$ai_generation", "$ai_metric"]),
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

        # Apply property filters from conditions
        condition_exprs: list[ast.Expr] = []
        for condition in conditions:
            props = condition.get("properties", [])
            if props:
                expr = property_to_expr(props, team)
                condition_exprs.append(expr)

        if condition_exprs:
            if len(condition_exprs) == 1:
                where_exprs.append(condition_exprs[0])
            else:
                where_exprs.append(ast.Or(exprs=condition_exprs))

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

            result = run_hog_eval(bytecode, event_data)

            if event_type == "$ai_generation":
                input_raw = properties.get("$ai_input") or properties.get("$ai_input_state", "")
                output_raw = (
                    properties.get("$ai_output_choices")
                    or properties.get("$ai_output")
                    or properties.get("$ai_output_state", "")
                )
            else:
                input_raw = properties.get("$ai_input_state", "")
                output_raw = properties.get("$ai_output_state", "")

            input_preview = extract_text_from_messages(input_raw)[:200]
            output_preview = extract_text_from_messages(output_raw)[:200]

            results.append(
                {
                    "event_uuid": event_uuid,
                    "trace_id": properties.get("$ai_trace_id"),
                    "input_preview": input_preview,
                    "output_preview": output_preview,
                    "result": result["verdict"],
                    "reasoning": result["reasoning"],
                    "error": result["error"],
                }
            )

        return Response({"results": results})


class TestHogRequestSerializer(serializers.Serializer):
    source = serializers.CharField(required=True, min_length=1)
    sample_count = serializers.IntegerField(required=False, default=5, min_value=1, max_value=10)
    conditions = serializers.ListField(child=serializers.DictField(), required=False, default=list)
