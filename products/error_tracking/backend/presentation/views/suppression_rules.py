import structlog
import posthoganalytics
from drf_spectacular.utils import OpenApiResponse, extend_schema_field
from pydantic import ValidationError as PydanticValidationError
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from posthog.schema import PropertyGroupFilterValue

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.event_usage import groups

from products.error_tracking.backend.facade import api as error_tracking_api

logger = structlog.get_logger(__name__)


class ErrorTrackingSuppressionRuleSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    filters = serializers.JSONField()
    order_key = serializers.IntegerField()
    disabled_data = serializers.JSONField(allow_null=True)
    sampling_rate = serializers.FloatField()
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


@extend_schema_field(PropertyGroupFilterValue)  # type: ignore[arg-type]
class ErrorTrackingSuppressionRuleFiltersField(serializers.JSONField):
    def to_internal_value(self, data):
        value = super().to_internal_value(data)

        if not isinstance(value, dict):
            raise serializers.ValidationError("Expected an object.")

        if error_tracking_api.has_filter_values(value):
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


class ErrorTrackingSuppressionRuleViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "error_tracking"
    serializer_class = ErrorTrackingSuppressionRuleSerializer

    def list(self, request, *args, **kwargs) -> Response:
        rules = error_tracking_api.list_suppression_rules(self.team.id)
        page = self.paginate_queryset(rules)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(rules, many=True).data)

    def retrieve(self, request, *args, pk=None, **kwargs) -> Response:
        rule = error_tracking_api.get_suppression_rule(self.team.id, pk)
        if rule is None:
            raise NotFound()
        return Response(self.get_serializer(rule).data)

    def _apply_rule_update(self, request: ValidatedRequest, pk: str) -> Response:
        try:
            rule = error_tracking_api.update_suppression_rule(
                self.team.id,
                pk,
                filters=request.validated_data.get("filters"),
                sampling_rate=request.validated_data.get("sampling_rate"),
            )
        except error_tracking_api.InvalidBytecodeError as err:
            raise ValidationError(str(err)) from err
        if rule is None:
            raise NotFound()
        posthoganalytics.capture(
            "error_tracking_suppression_rule_edited",
            groups=groups(self.team.organization, self.team),
        )
        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)

    @validated_request(
        request_serializer=ErrorTrackingSuppressionRuleUpdateRequestSerializer,
        responses={204: None},
    )
    def update(self, request: ValidatedRequest, *args, pk=None, **kwargs) -> Response:
        return self._apply_rule_update(request, pk)

    @validated_request(
        request_serializer=ErrorTrackingSuppressionRuleUpdateRequestSerializer,
        responses={204: None},
    )
    def partial_update(self, request: ValidatedRequest, *args, pk=None, **kwargs) -> Response:
        return self._apply_rule_update(request, pk)

    def destroy(self, request, *args, pk=None, **kwargs) -> Response:
        if not error_tracking_api.delete_suppression_rule(self.team.id, pk):
            raise NotFound()
        posthoganalytics.capture(
            "error_tracking_suppression_rule_deleted",
            groups=groups(self.team.organization, self.team),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @validated_request(
        request_serializer=ErrorTrackingSuppressionRuleCreateRequestSerializer,
        responses={201: OpenApiResponse(response=ErrorTrackingSuppressionRuleSerializer)},
    )
    def create(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        filters = request.validated_data.get("filters")
        if filters is None:
            filters = {"type": "AND", "values": []}
        try:
            rule = error_tracking_api.create_suppression_rule(
                self.team.id,
                filters=filters,
                sampling_rate=request.validated_data["sampling_rate"],
            )
        except error_tracking_api.InvalidBytecodeError as err:
            raise ValidationError(str(err)) from err
        posthoganalytics.capture(
            "error_tracking_suppression_rule_created",
            groups=groups(self.team.organization, self.team),
        )
        return Response(self.get_serializer(rule).data, status=status.HTTP_201_CREATED)

    @action(methods=["PATCH"], detail=False)
    def reorder(self, request, **kwargs) -> Response:
        orders: dict[str, int] = request.data.get("orders", {})
        error_tracking_api.reorder_suppression_rules(self.team.id, orders)
        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)
