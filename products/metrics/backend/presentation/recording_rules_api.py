"""DRF views for metrics recording rules: PromQL queries that are written back into the project's metrics."""

from dataclasses import asdict
from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User
from posthog.permissions import PostHogFeatureFlagPermission, posthog_feature_flag_enabled

from products.metrics.backend.facade.api import (
    create_recording_rule,
    delete_recording_rule,
    get_recording_rule,
    list_recording_rules,
    update_recording_rule,
)
from products.metrics.backend.facade.contracts import (
    MAX_PROMQL_LENGTH,
    METRICS_FEATURE_FLAG,
    METRICS_RECORDING_RULES_FEATURE_FLAG,
    RecordingRuleError,
    RecordingRuleNotFound,
)

__all__ = ["MetricsRecordingRuleViewSet"]

UUID_REGEX = "[0-9a-fA-F-]{36}"


class MetricsRecordingRuleSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Recording rule id.")
    metric_name = serializers.CharField(
        max_length=200,
        help_text="The metric the rule writes, in the level:metric:operations form, for example "
        "job:http_errors:rate5m. It must contain a colon and cannot change after create.",
    )
    query = serializers.CharField(
        max_length=MAX_PROMQL_LENGTH,
        help_text="A PromQL expression over this project's metrics that returns an instant vector or a scalar. "
        "Each series it returns is written as one series of `metric_name`, with the same labels.",
    )
    description = serializers.CharField(
        required=False, allow_blank=True, default="", help_text="What the recorded metric means."
    )
    enabled = serializers.BooleanField(
        required=False, default=True, help_text="When false, the rule is kept but not evaluated."
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the rule was created.")
    updated_at = serializers.DateTimeField(read_only=True, help_text="When the rule was last changed.")
    last_evaluated_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="The minute the rule last wrote a result. Null until it first writes.",
    )
    last_series_count = serializers.IntegerField(
        read_only=True, allow_null=True, help_text="How many series the last result had."
    )
    last_error = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Why the last evaluation wrote nothing. Null when the last evaluation wrote a result.",
    )


class MetricsRecordingRuleUpdateSerializer(serializers.Serializer):
    query = serializers.CharField(
        required=False, max_length=MAX_PROMQL_LENGTH, help_text="A new PromQL expression for the rule."
    )
    description = serializers.CharField(required=False, allow_blank=True, help_text="What the recorded metric means.")
    enabled = serializers.BooleanField(required=False, help_text="When false, the rule is kept but not evaluated.")


class MetricsRecordingRuleViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Recording rules evaluate a PromQL query every minute and write its result into this project's metrics
    under a new metric name, so dashboards and alerts can read the stored result instead of the query."""

    scope_object = "metrics"
    serializer_class = _FallbackSerializer
    posthog_feature_flag = METRICS_FEATURE_FLAG
    permission_classes = [PostHogFeatureFlagPermission]
    lookup_value_regex = UUID_REGEX

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        if not posthog_feature_flag_enabled(
            METRICS_RECORDING_RULES_FEATURE_FLAG,
            str(cast(User, request.user).distinct_id),
            organization_id=self.team.organization_id,
            team_id=self.team.pk,
        ):
            raise PermissionDenied("Recording rules are not enabled for this project.")

    @extend_schema(responses={200: MetricsRecordingRuleSerializer(many=True)})
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """The project's recording rules, by metric name."""
        rules = list_recording_rules(team=self.team)
        return Response(MetricsRecordingRuleSerializer([asdict(rule) for rule in rules], many=True).data)

    @extend_schema(responses={200: MetricsRecordingRuleSerializer})
    def retrieve(self, request: Request, pk: str | None = None, *args: Any, **kwargs: Any) -> Response:
        try:
            rule = get_recording_rule(team=self.team, rule_id=str(pk))
        except RecordingRuleNotFound as error:
            raise NotFound(str(error))
        return Response(MetricsRecordingRuleSerializer(asdict(rule)).data)

    @extend_schema(
        request=MetricsRecordingRuleSerializer,
        responses={
            201: MetricsRecordingRuleSerializer,
            400: OpenApiResponse(description="The rule is not valid, or the project has too many rules."),
        },
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Create a recording rule. It writes its first result within about a minute."""
        serializer = MetricsRecordingRuleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            rule = create_recording_rule(team=self.team, user=cast(User, request.user), **serializer.validated_data)
        except RecordingRuleError as error:
            raise ValidationError(str(error))
        return Response(MetricsRecordingRuleSerializer(asdict(rule)).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=MetricsRecordingRuleUpdateSerializer,
        responses={
            200: MetricsRecordingRuleSerializer,
            400: OpenApiResponse(description="The edit is not valid, or it tries to change the metric name."),
        },
    )
    def partial_update(self, request: Request, pk: str | None = None, *args: Any, **kwargs: Any) -> Response:
        """Change a rule's query, description or enabled state. The metric name cannot change."""
        if "metric_name" in request.data:
            raise ValidationError({"metric_name": "The metric name cannot change. Create a new rule instead."})
        serializer = MetricsRecordingRuleUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            rule = update_recording_rule(team=self.team, rule_id=str(pk), **serializer.validated_data)
        except RecordingRuleNotFound as error:
            raise NotFound(str(error))
        except RecordingRuleError as error:
            raise ValidationError(str(error))
        return Response(MetricsRecordingRuleSerializer(asdict(rule)).data)

    @extend_schema(responses={204: None})
    def destroy(self, request: Request, pk: str | None = None, *args: Any, **kwargs: Any) -> Response:
        """Delete a rule. The series it already wrote stay until the project's metrics retention removes them."""
        try:
            delete_recording_rule(team=self.team, rule_id=str(pk))
        except RecordingRuleNotFound as error:
            raise NotFound(str(error))
        return Response(status=status.HTTP_204_NO_CONTENT)
