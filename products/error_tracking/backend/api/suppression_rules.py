from typing import override

import structlog
import posthoganalytics
from drf_spectacular.utils import OpenApiResponse, extend_schema_field
from pydantic import ValidationError as PydanticValidationError
from rest_framework import serializers, status, viewsets
from rest_framework.response import Response

from posthog.schema import PropertyGroupFilterValue

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import groups
from posthog.models.team.team import Team

from products.error_tracking.backend.models import ErrorTrackingSuppressionRule

from .utils import RuleReorderingMixin, generate_byte_code, generate_match_all_bytecode, has_filter_values

logger = structlog.get_logger(__name__)


class ErrorTrackingSuppressionRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingSuppressionRule
        fields = ["id", "filters", "order_key", "disabled_data", "sampling_rate", "created_at", "updated_at"]
        read_only_fields = ["team_id", "created_at", "updated_at"]


@extend_schema_field(PropertyGroupFilterValue)  # type: ignore[arg-type]
class ErrorTrackingSuppressionRuleFiltersField(serializers.JSONField):
    def to_internal_value(self, data):
        value = super().to_internal_value(data)

        if not isinstance(value, dict):
            raise serializers.ValidationError("Expected an object.")

        if has_filter_values(value):
            try:
                PropertyGroupFilterValue(**value)
            except (PydanticValidationError, TypeError) as err:
                logger.warning("Invalid suppression rule filters payload", exc_info=err)
                raise serializers.ValidationError("Invalid filters payload.") from err
        elif "values" not in value:
            raise serializers.ValidationError("Invalid filters")

        return value


class ErrorTrackingSuppressionRuleCreateRequestSerializer(serializers.Serializer):
    filters = ErrorTrackingSuppressionRuleFiltersField(
        required=False,
        help_text=(
            "Optional property-group filters that define which incoming error events should be suppressed. "
            "Omit this field or provide an empty `values` array to create a match-all suppression rule."
        ),
    )
    sampling_rate = serializers.FloatField(
        required=False,
        default=1.0,
        min_value=0.0,
        max_value=1.0,
        help_text=(
            "Probability that a matching event is dropped. `1.0` drops every match (default); `0.0` drops none; "
            "`0.5` drops half. Higher values suppress more."
        ),
    )


class ErrorTrackingSuppressionRuleUpdateRequestSerializer(serializers.Serializer):
    filters = ErrorTrackingSuppressionRuleFiltersField(
        required=False,
        help_text=(
            "Property-group filters that define which incoming error events should be suppressed. "
            "Provide an empty `values` array to convert the rule into a match-all suppression. "
            "Omit to preserve the existing filters."
        ),
    )
    sampling_rate = serializers.FloatField(
        required=False,
        min_value=0.0,
        max_value=1.0,
        help_text=(
            "Probability that a matching event is dropped. `1.0` drops every match; `0.0` drops none; "
            "`0.5` drops half. Higher values suppress more. Omit to preserve the existing rate."
        ),
    )


class ErrorTrackingSuppressionRuleViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet, RuleReorderingMixin):
    scope_object = "error_tracking"
    queryset = ErrorTrackingSuppressionRule.objects.order_by("order_key").all()
    serializer_class = ErrorTrackingSuppressionRuleSerializer

    @override
    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team.id)

    def _apply_rule_update(self, request: ValidatedRequest) -> Response:
        suppression_rule = self.get_object()
        json_filters = request.validated_data.get("filters")

        if json_filters is not None:
            if has_filter_values(json_filters):
                parsed_filters = PropertyGroupFilterValue(**json_filters)
                suppression_rule.filters = json_filters
                suppression_rule.bytecode = generate_byte_code(self.team, parsed_filters)
            else:
                suppression_rule.filters = json_filters
                suppression_rule.bytecode = generate_match_all_bytecode()
        if "sampling_rate" in request.validated_data:
            suppression_rule.sampling_rate = request.validated_data["sampling_rate"]
        suppression_rule.disabled_data = None
        suppression_rule.save()

        posthoganalytics.capture(
            "error_tracking_suppression_rule_edited",
            groups=groups(self.team.organization, self.team),
        )

        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)

    @override
    @validated_request(
        request_serializer=ErrorTrackingSuppressionRuleUpdateRequestSerializer,
        responses={204: None},
    )
    def update(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        return self._apply_rule_update(request)

    @override
    @validated_request(
        request_serializer=ErrorTrackingSuppressionRuleUpdateRequestSerializer,
        responses={204: None},
    )
    def partial_update(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        return self._apply_rule_update(request)

    @override
    def destroy(self, request, *args, **kwargs) -> Response:
        response = super().destroy(request, *args, **kwargs)

        posthoganalytics.capture(
            "error_tracking_suppression_rule_deleted",
            groups=groups(self.team.organization, self.team),
        )

        return response

    @validated_request(
        request_serializer=ErrorTrackingSuppressionRuleCreateRequestSerializer,
        responses={201: OpenApiResponse(response=ErrorTrackingSuppressionRuleSerializer)},
    )
    def create(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        json_filters = request.validated_data.get("filters")

        if json_filters is None:
            json_filters = {"type": "AND", "values": []}

        if has_filter_values(json_filters):
            bytecode = generate_byte_code(self.team, PropertyGroupFilterValue(**json_filters))
        else:
            bytecode = generate_match_all_bytecode()

        sampling_rate = request.validated_data["sampling_rate"]

        suppression_rule = ErrorTrackingSuppressionRule.objects.create(
            team=self.team,
            filters=json_filters,
            bytecode=bytecode,
            order_key=0,
            sampling_rate=sampling_rate,
        )

        posthoganalytics.capture(
            "error_tracking_suppression_rule_created",
            groups=groups(self.team.organization, self.team),
        )

        serializer = ErrorTrackingSuppressionRuleSerializer(suppression_rule)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


# Properties that require server-side symbol resolution to have meaningful
# values. Client-side these will contain minified/bundled names.
SERVER_ONLY_PROPERTIES = frozenset({"$exception_sources", "$exception_functions"})


def _get_client_safe_filters(filters: dict) -> dict | None:
    """Return the filters if every leaf is client-safe, otherwise None.

    If any filter in the tree uses a server-only property, the entire rule
    is not evaluated client-side.
    """
    for value in filters.get("values", []):
        if "key" in value:
            if value.get("key") in SERVER_ONLY_PROPERTIES:
                return None
        elif "values" in value:
            if _get_client_safe_filters(value) is None:
                return None
    return filters


def get_client_safe_suppression_rules(team: Team) -> list[dict]:
    rules = list(ErrorTrackingSuppressionRule.objects.filter(team=team).values_list("filters", "sampling_rate"))
    result = []
    for filters, sampling_rate in rules:
        safe = _get_client_safe_filters(filters)
        if safe is not None:
            rule_data = {**safe}
            if sampling_rate < 1.0:
                rule_data["samplingRate"] = sampling_rate
            result.append(rule_data)
    return result
