from typing import Any, cast

from django.db.models import Q, QuerySet

import structlog
import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.models import User

from ..models.evaluation_configs import validate_evaluation_configs
from ..models.evaluations import Evaluation

logger = structlog.get_logger(__name__)


class EvaluationSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

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

    def create(self, validated_data):
        request = self.context["request"]
        validated_data["team"] = self.context["get_team"]()
        validated_data["created_by"] = request.user
        return super().create(validated_data)


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


class EvaluationViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "evaluation"
    permission_classes = [IsAuthenticated]
    serializer_class = EvaluationSerializer
    queryset = Evaluation.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_class = EvaluationFilter

    def safely_get_queryset(self, queryset: QuerySet[Evaluation]) -> QuerySet[Evaluation]:
        queryset = queryset.filter(team_id=self.team_id).select_related("created_by").order_by("-created_at")
        if not self.action.endswith("update"):
            queryset = queryset.filter(deleted=False)

        return queryset

    def perform_create(self, serializer):
        instance = serializer.save()

        # Calculate properties for tracking
        conditions = instance.conditions or []
        condition_count = len(conditions)
        has_rollout_percentage = any(condition.get("rollout_percentage", 100) < 100 for condition in conditions)

        # Get prompt length if available
        prompt_length = 0
        if instance.evaluation_config and isinstance(instance.evaluation_config, dict):
            prompt = instance.evaluation_config.get("prompt", "")
            if isinstance(prompt, str):
                prompt_length = len(prompt)

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
                "prompt_length": prompt_length,
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
        prompt_changed = False

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
                        # Check if prompt changed
                        old_prompt = old_value.get("prompt", "") if isinstance(old_value, dict) else ""
                        new_prompt = new_value.get("prompt", "") if isinstance(new_value, dict) else ""
                        if old_prompt != new_prompt:
                            prompt_changed = True

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
            if prompt_changed:
                event_properties["prompt_changed"] = True

            report_user_action(
                cast(User, self.request.user),
                "llma evaluation updated",
                event_properties,
                self.team,
            )
