from __future__ import annotations

from typing import Any, cast

from django.db import transaction
from django.db.models import F, Max, QuerySet

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models.activity_logging.activity_log import ActivityScope, Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.models.user import User
from posthog.permissions import PostHogFeatureFlagPermission

from products.logs.backend.models import LogsExclusionRule


class LogsSamplingRuleSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique identifier for this sampling rule.")
    name = serializers.CharField(max_length=255, help_text="User-visible label for this rule.")
    enabled = serializers.BooleanField(
        default=False,
        help_text="When false, the rule is ignored by ingestion and listing UIs that show active rules only.",
    )
    priority = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        help_text="Lower numbers are evaluated first; the first matching rule wins. Omit to append after existing rules.",
    )
    rule_type = serializers.ChoiceField(
        choices=LogsExclusionRule.RuleType.choices,
        help_text="Rule kind: severity_sampling, path_drop, or rate_limit (rate_limit reserved for a future release).",
    )
    scope_service = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=False,
        max_length=512,
        help_text="If set, the rule applies only to this service name; null means all services.",
    )
    scope_path_pattern = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=False,
        max_length=1024,
        help_text="Optional regex matched against a path-like log attribute when present.",
    )
    scope_attribute_filters = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        default=list,
        help_text='Optional list of predicates over string attributes, e.g. [{"key":"http.route","op":"eq","value":"/api"}].',
    )
    config = serializers.JSONField(
        help_text="Type-specific JSON (severity actions, path_drop patterns, or future rate_limit settings)."
    )
    version = serializers.IntegerField(
        read_only=True, help_text="Incremented on each update for worker cache coherency."
    )
    created_by: serializers.PrimaryKeyRelatedField = serializers.PrimaryKeyRelatedField(read_only=True)  # ty: ignore[invalid-assignment]

    class Meta:
        model = LogsExclusionRule
        fields = [
            "id",
            "name",
            "enabled",
            "priority",
            "rule_type",
            "scope_service",
            "scope_path_pattern",
            "scope_attribute_filters",
            "config",
            "version",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "version", "created_by", "created_at", "updated_at"]

    def validate_scope_attribute_filters(self, value: Any) -> Any:
        if not isinstance(value, list):
            raise ValidationError("scope_attribute_filters must be a list.")
        for i, item in enumerate(value):
            if not isinstance(item, dict):
                raise ValidationError({str(i): "Each filter must be an object."})
            if "key" not in item or "op" not in item:
                raise ValidationError({str(i): "Each filter must include key and op."})
        return value


class LogsSamplingRuleReorderSerializer(serializers.Serializer):
    ordered_ids = serializers.ListField(
        child=serializers.UUIDField(),
        help_text="Rule IDs in the desired evaluation order (first element is highest priority / lowest order index).",
    )


class LogsSamplingRuleSimulateResponseSerializer(serializers.Serializer):
    estimated_reduction_pct = serializers.FloatField(
        help_text="Rough percent of log volume this rule would drop (0–100). Stub until ClickHouse-backed estimate ships."
    )
    notes = serializers.CharField(help_text="Human-readable caveats for the estimate.")


@extend_schema(tags=["logs"])
class LogsSamplingRuleViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "logs"
    queryset = LogsExclusionRule.objects.all().order_by("priority", "created_at")
    serializer_class = LogsSamplingRuleSerializer
    lookup_field = "id"
    posthog_feature_flag = "logs-sampling-rules"
    permission_classes = [PostHogFeatureFlagPermission]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(team_id=self.team_id)

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        s = cast(LogsSamplingRuleSerializer, serializer)
        user = cast(User, self.request.user)
        max_priority = LogsExclusionRule.objects.filter(team_id=self.team_id).aggregate(m=Max("priority"))["m"] or -1
        raw_priority = s.validated_data.pop("priority", None)
        priority = max_priority + 1 if raw_priority is None else int(raw_priority)
        instance = s.save(
            team_id=self.team_id,
            created_by=user if user.is_authenticated else None,
            priority=priority,
            version=1,
        )
        report_user_action(
            user,
            "logs sampling rule created",
            {"rule_id": str(instance.id), "rule_type": instance.rule_type},
            team=self.team,
            request=self.request,
        )

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        s = cast(LogsSamplingRuleSerializer, serializer)
        user = cast(User, self.request.user)
        instance = cast(LogsExclusionRule, s.save())
        LogsExclusionRule.objects.filter(pk=instance.pk, team_id=self.team_id).update(version=F("version") + 1)
        instance.refresh_from_db(fields=["version", "updated_at"])
        report_user_action(
            user,
            "logs sampling rule updated",
            {"rule_id": str(instance.id), "rule_type": instance.rule_type},
            team=self.team,
            request=self.request,
        )

    def perform_destroy(self, instance: LogsExclusionRule) -> None:
        user = cast(User, self.request.user)
        report_user_action(
            user,
            "logs sampling rule deleted",
            {"rule_id": str(instance.id)},
            team=self.team,
            request=self.request,
        )
        super().perform_destroy(instance)

    @extend_schema(
        request=LogsSamplingRuleReorderSerializer,
        responses={200: LogsSamplingRuleSerializer(many=True)},
        description="Atomically reassign priorities so the given ID order maps to ascending priorities (0..n-1).",
    )
    @action(detail=False, methods=["post"], url_path="reorder")
    def reorder(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = LogsSamplingRuleReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ordered_ids = serializer.validated_data["ordered_ids"]
        team_rule_ids = set(LogsExclusionRule.objects.filter(team_id=self.team_id).values_list("id", flat=True))
        if set(ordered_ids) != team_rule_ids or len(ordered_ids) != len(team_rule_ids):
            raise ValidationError("ordered_ids must list every sampling rule for this team exactly once.")
        with transaction.atomic():
            for index, rid in enumerate(ordered_ids):
                LogsExclusionRule.objects.filter(id=rid, team_id=self.team_id).update(
                    priority=index,
                    version=F("version") + 1,
                )
        qs = self.safely_get_queryset(LogsExclusionRule.objects.all()).order_by("priority", "created_at")
        return Response(LogsSamplingRuleSerializer(qs, many=True).data, status=status.HTTP_200_OK)

    @extend_schema(
        request=None,
        responses={200: LogsSamplingRuleSimulateResponseSerializer},
        description="Dry-run estimate for how much volume this rule would remove (placeholder response until CH-backed simulation is wired).",
    )
    @action(detail=True, methods=["post"], url_path="simulate")
    def simulate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        _ = self.get_object()
        return Response(
            {
                "estimated_reduction_pct": 0.0,
                "notes": "Simulation not yet implemented against ClickHouse.",
            },
            status=status.HTTP_200_OK,
        )


@mutable_receiver(model_activity_signal, sender=LogsExclusionRule)
def handle_logs_sampling_rule_activity(
    sender: Any,
    scope: str,
    before_update: LogsExclusionRule | None,
    after_update: LogsExclusionRule | None,
    activity: str,
    user: User | None,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    instance = after_update or before_update
    if instance is None:
        return
    log_activity(
        organization_id=instance.team.organization_id,
        team_id=instance.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=instance.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(cast(ActivityScope, scope), previous=before_update, current=after_update),
            name=instance.name,
        ),
    )
