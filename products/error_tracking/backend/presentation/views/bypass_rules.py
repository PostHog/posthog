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


class ErrorTrackingBypassRuleSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique identifier of the bypass rule.")
    filters = serializers.JSONField(
        help_text="Property-group filters that define which incoming error events bypass rate limiting."
    )
    order_key = serializers.IntegerField(
        help_text="Position of the rule in the team's ordered list. Rules are evaluated greedily in ascending order."
    )
    disabled_data = serializers.JSONField(
        allow_null=True,
        help_text=(
            "Populated when the rule has been automatically disabled (for example, after its filters failed to "
            "evaluate during ingestion). Null while the rule is active."
        ),
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the rule was created.")
    updated_at = serializers.DateTimeField(read_only=True, help_text="When the rule was last updated.")


@extend_schema_field(PropertyGroupFilterValue)  # type: ignore[arg-type]
class ErrorTrackingBypassRuleFiltersField(serializers.JSONField):
    def to_internal_value(self, data):
        value = super().to_internal_value(data)

        if not isinstance(value, dict):
            raise serializers.ValidationError("Expected an object.")

        # A bypass rule must target specific exceptions. Empty or keyless filters compile to a
        # match-all rule that bypasses all rate limiting for the project — use the rate limit
        # settings to disable rate limiting instead of creating a catch-all bypass rule.
        if not error_tracking_api.has_filter_values(value):
            raise serializers.ValidationError("A bypass rule must have at least one filter.")

        try:
            PropertyGroupFilterValue(**value)
        except (PydanticValidationError, TypeError) as err:
            logger.warning("Invalid bypass rule filters payload", exc_info=err)
            raise serializers.ValidationError("Invalid filters payload.") from err

        return value


class ErrorTrackingBypassRuleCreateRequestSerializer(serializers.Serializer):
    filters = ErrorTrackingBypassRuleFiltersField(
        required=True,
        help_text=(
            "Property-group filters that define which incoming error events bypass rate limiting. "
            "Must contain at least one filter — empty rules are rejected. To stop rate limiting "
            "entirely, adjust the rate limit settings instead of creating a match-all bypass rule."
        ),
    )


class ErrorTrackingBypassRuleUpdateRequestSerializer(serializers.Serializer):
    filters = ErrorTrackingBypassRuleFiltersField(
        required=False,
        help_text=(
            "Property-group filters that define which incoming error events bypass rate limiting. "
            "Must contain at least one filter. Omit to preserve the existing filters."
        ),
    )


class ErrorTrackingBypassRuleViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "error_tracking"
    serializer_class = ErrorTrackingBypassRuleSerializer

    def list(self, request, *args, **kwargs) -> Response:
        rules = error_tracking_api.list_bypass_rules(self.team.id)
        page = self.paginate_queryset(rules)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(rules, many=True).data)

    def retrieve(self, request, *args, pk=None, **kwargs) -> Response:
        rule = error_tracking_api.get_bypass_rule(self.team.id, pk)
        if rule is None:
            raise NotFound()
        return Response(self.get_serializer(rule).data)

    def _apply_rule_update(self, request: ValidatedRequest, pk: str) -> Response:
        try:
            rule = error_tracking_api.update_bypass_rule(
                self.team.id,
                pk,
                filters=request.validated_data.get("filters"),
            )
        except error_tracking_api.InvalidBytecodeError as err:
            raise ValidationError(str(err)) from err
        if rule is None:
            raise NotFound()
        posthoganalytics.capture(
            "error_tracking_bypass_rule_edited",
            groups=groups(self.team.organization, self.team),
        )
        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)

    @validated_request(
        request_serializer=ErrorTrackingBypassRuleUpdateRequestSerializer,
        responses={204: None},
    )
    def update(self, request: ValidatedRequest, *args, pk=None, **kwargs) -> Response:
        return self._apply_rule_update(request, pk)

    @validated_request(
        request_serializer=ErrorTrackingBypassRuleUpdateRequestSerializer,
        responses={204: None},
    )
    def partial_update(self, request: ValidatedRequest, *args, pk=None, **kwargs) -> Response:
        return self._apply_rule_update(request, pk)

    def destroy(self, request, *args, pk=None, **kwargs) -> Response:
        if not error_tracking_api.delete_bypass_rule(self.team.id, pk):
            raise NotFound()
        posthoganalytics.capture(
            "error_tracking_bypass_rule_deleted",
            groups=groups(self.team.organization, self.team),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @validated_request(
        request_serializer=ErrorTrackingBypassRuleCreateRequestSerializer,
        responses={201: OpenApiResponse(response=ErrorTrackingBypassRuleSerializer)},
    )
    def create(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        filters = request.validated_data["filters"]
        try:
            rule = error_tracking_api.create_bypass_rule(self.team.id, filters=filters)
        except error_tracking_api.InvalidBytecodeError as err:
            raise ValidationError(str(err)) from err
        posthoganalytics.capture(
            "error_tracking_bypass_rule_created",
            groups=groups(self.team.organization, self.team),
        )
        return Response(self.get_serializer(rule).data, status=status.HTTP_201_CREATED)

    @action(methods=["PATCH"], detail=False)
    def reorder(self, request, **kwargs) -> Response:
        orders: dict[str, int] = request.data.get("orders", {})
        error_tracking_api.reorder_bypass_rules(self.team.id, orders)
        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)
