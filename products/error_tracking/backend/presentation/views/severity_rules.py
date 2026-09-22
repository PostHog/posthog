import structlog
import posthoganalytics
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field, extend_schema_serializer
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
from products.error_tracking.backend.facade.contracts import ERROR_TRACKING_ISSUE_SEVERITIES

logger = structlog.get_logger(__name__)


@extend_schema_field(PropertyGroupFilterValue)  # type: ignore[arg-type]
class ErrorTrackingSeverityRuleFiltersField(serializers.JSONField):
    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if not isinstance(value, dict):
            raise serializers.ValidationError("Expected a JSON object.")
        try:
            PropertyGroupFilterValue(**value)
        except (PydanticValidationError, TypeError) as err:
            logger.warning("Invalid severity rule filters payload", exc_info=err)
            raise serializers.ValidationError("Invalid filters payload.") from err
        return value


@extend_schema_field(
    {
        "type": "object",
        "nullable": True,
        "properties": {
            "message": {"type": "string"},
            "issue": {"type": "object", "additionalProperties": True},
            "properties": {"type": "object", "additionalProperties": True},
        },
    }
)
class ErrorTrackingSeverityRuleDisabledDataField(serializers.JSONField):
    pass


class ErrorTrackingSeverityRuleSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique identifier of the severity rule.")
    filters = ErrorTrackingSeverityRuleFiltersField(
        help_text="Property-group filters evaluated against the event that creates an issue."
    )
    severity = serializers.ChoiceField(
        choices=ERROR_TRACKING_ISSUE_SEVERITIES,
        help_text="Severity assigned to a newly created issue when this rule is the first match.",
    )
    order_key = serializers.IntegerField(
        help_text="Evaluation priority. Lower values run first, and the first matching rule wins."
    )
    disabled_data = ErrorTrackingSeverityRuleDisabledDataField(
        allow_null=True,
        help_text="Diagnostic details when ingestion automatically disables the rule, otherwise null.",
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the rule was created.")
    updated_at = serializers.DateTimeField(read_only=True, help_text="When the rule was last updated.")


@extend_schema_serializer(many=False)
class ErrorTrackingSeverityRuleListResponseSerializer(serializers.Serializer):
    results = ErrorTrackingSeverityRuleSerializer(many=True, help_text="Severity rules in ascending evaluation order.")


class ErrorTrackingSeverityRuleCreateRequestSerializer(serializers.Serializer):
    filters = ErrorTrackingSeverityRuleFiltersField(
        help_text="Property-group filters evaluated against the event that creates an issue."
    )
    severity = serializers.ChoiceField(
        choices=ERROR_TRACKING_ISSUE_SEVERITIES,
        help_text="Severity assigned when this rule is the first match.",
    )
    order_key = serializers.IntegerField(
        required=False,
        default=0,
        help_text="Evaluation priority. Lower values run first. Defaults to 0.",
    )


class ErrorTrackingSeverityRuleUpdateRequestSerializer(serializers.Serializer):
    filters = ErrorTrackingSeverityRuleFiltersField(
        required=False,
        help_text="Replacement property-group filters. Omit to preserve the existing filters.",
    )
    severity = serializers.ChoiceField(
        choices=ERROR_TRACKING_ISSUE_SEVERITIES,
        required=False,
        help_text="Replacement severity. Omit to preserve the existing severity.",
    )


class ErrorTrackingSeverityRuleReorderRequestSerializer(serializers.Serializer):
    orders = serializers.DictField(
        child=serializers.IntegerField(),
        help_text="Mapping from severity rule UUID to its new evaluation order.",
    )


class ErrorTrackingSeverityRuleViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "error_tracking"
    scope_object_write_actions = ["create", "update", "partial_update", "destroy", "reorder"]
    requires_resource_level_access = True
    serializer_class = ErrorTrackingSeverityRuleSerializer
    pagination_class = None

    @extend_schema(responses={200: OpenApiResponse(response=ErrorTrackingSeverityRuleListResponseSerializer)})
    def list(self, request, *args, **kwargs) -> Response:
        rules = error_tracking_api.list_severity_rules(self.team.id)
        return Response({"results": self.get_serializer(rules, many=True).data})

    def retrieve(self, request, *args, pk=None, **kwargs) -> Response:
        rule = error_tracking_api.get_severity_rule(self.team.id, pk)
        if rule is None:
            raise NotFound()
        return Response(self.get_serializer(rule).data)

    def _apply_rule_update(self, request: ValidatedRequest, pk: str) -> Response:
        try:
            rule = error_tracking_api.update_severity_rule(
                self.team.id,
                pk,
                filters=request.validated_data.get("filters"),
                severity=request.validated_data.get("severity"),
            )
        except (error_tracking_api.InvalidBytecodeError, error_tracking_api.SeverityRuleLimitError) as err:
            raise ValidationError(str(err)) from err
        if rule is None:
            raise NotFound()
        posthoganalytics.capture(
            "error_tracking_severity_rule_edited",
            distinct_id=request.user.pk,
            groups=groups(self.team.organization, self.team),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @validated_request(request_serializer=ErrorTrackingSeverityRuleUpdateRequestSerializer, responses={204: None})
    def update(self, request: ValidatedRequest, *args, pk=None, **kwargs) -> Response:
        return self._apply_rule_update(request, pk)

    @validated_request(request_serializer=ErrorTrackingSeverityRuleUpdateRequestSerializer, responses={204: None})
    def partial_update(self, request: ValidatedRequest, *args, pk=None, **kwargs) -> Response:
        return self._apply_rule_update(request, pk)

    def destroy(self, request, *args, pk=None, **kwargs) -> Response:
        if not error_tracking_api.delete_severity_rule(self.team.id, pk):
            raise NotFound()
        posthoganalytics.capture(
            "error_tracking_severity_rule_deleted",
            distinct_id=request.user.pk,
            groups=groups(self.team.organization, self.team),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @validated_request(
        request_serializer=ErrorTrackingSeverityRuleCreateRequestSerializer,
        responses={201: OpenApiResponse(response=ErrorTrackingSeverityRuleSerializer)},
    )
    def create(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        try:
            rule = error_tracking_api.create_severity_rule(
                self.team.id,
                filters=request.validated_data["filters"],
                severity=request.validated_data["severity"],
                order_key=request.validated_data["order_key"],
            )
        except (error_tracking_api.InvalidBytecodeError, error_tracking_api.SeverityRuleLimitError) as err:
            raise ValidationError(str(err)) from err
        posthoganalytics.capture(
            "error_tracking_severity_rule_created",
            distinct_id=request.user.pk,
            groups=groups(self.team.organization, self.team),
        )
        return Response(self.get_serializer(rule).data, status=status.HTTP_201_CREATED)

    @validated_request(request_serializer=ErrorTrackingSeverityRuleReorderRequestSerializer, responses={204: None})
    @action(methods=["PATCH"], detail=False)
    def reorder(self, request: ValidatedRequest, **kwargs) -> Response:
        error_tracking_api.reorder_severity_rules(self.team.id, request.validated_data["orders"])
        return Response(status=status.HTTP_204_NO_CONTENT)
