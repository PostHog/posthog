from uuid import UUID

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

from products.error_tracking.backend.models import ErrorTrackingAssignmentRule

from .utils import RuleReorderingMixin, generate_byte_code

logger = structlog.get_logger(__name__)


@extend_schema_field(PropertyGroupFilterValue)  # type: ignore[arg-type]
class ErrorTrackingAssignmentRuleFiltersField(serializers.JSONField):
    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if not isinstance(value, dict):
            raise serializers.ValidationError("Expected a JSON object.")
        try:
            PropertyGroupFilterValue(**value)
        except PydanticValidationError as err:
            logger.warning("Invalid assignment rule filters payload", exc_info=err)
            raise serializers.ValidationError("Invalid filters payload.") from err
        return value


@extend_schema_field({"oneOf": [{"type": "integer"}, {"type": "string", "format": "uuid"}]})
class ErrorTrackingAssignmentRuleAssigneeIdField(serializers.Field):
    def to_internal_value(self, data):
        if isinstance(data, bool):
            raise serializers.ValidationError("Expected an integer user ID or UUID role ID.")
        if isinstance(data, int):
            return data
        if isinstance(data, str):
            try:
                return UUID(data)
            except ValueError:
                if data.isdigit():
                    return int(data)
        raise serializers.ValidationError("Expected an integer user ID or UUID role ID.")

    def to_representation(self, value):
        return value


class ErrorTrackingAssignmentRuleAssigneeRequestSerializer(serializers.Serializer):
    type = serializers.ChoiceField(
        choices=["user", "role"],
        help_text="Assignee type. Use `user` for a user ID or `role` for a role UUID.",
    )
    id = ErrorTrackingAssignmentRuleAssigneeIdField(
        help_text="User ID when `type` is `user`, or role UUID when `type` is `role`."
    )

    def validate(self, attrs):
        assignee_id = attrs["id"]
        if attrs["type"] == "user" and not isinstance(assignee_id, int):
            raise serializers.ValidationError({"id": "User assignee IDs must be integers."})
        if attrs["type"] == "role" and not isinstance(assignee_id, UUID):
            raise serializers.ValidationError({"id": "Role assignee IDs must be UUIDs."})
        return attrs


class ErrorTrackingAssignmentRuleCreateRequestSerializer(serializers.Serializer):
    filters = ErrorTrackingAssignmentRuleFiltersField(
        help_text="Property-group filters that define when this rule matches incoming error events."
    )
    assignee = ErrorTrackingAssignmentRuleAssigneeRequestSerializer(
        help_text="User or role to assign matching issues to."
    )


class ErrorTrackingAssignmentRuleUpdateRequestSerializer(serializers.Serializer):
    filters = ErrorTrackingAssignmentRuleFiltersField(
        required=False,
        allow_null=True,
        help_text="Property-group filters that define when this rule matches incoming error events.",
    )
    assignee = ErrorTrackingAssignmentRuleAssigneeRequestSerializer(
        required=False,
        allow_null=True,
        help_text="User or role to assign matching issues to.",
    )


class ErrorTrackingAssignmentRuleSerializer(serializers.ModelSerializer):
    assignee = serializers.SerializerMethodField()

    class Meta:
        model = ErrorTrackingAssignmentRule
        fields = ["id", "filters", "assignee", "order_key", "disabled_data", "created_at", "updated_at"]
        read_only_fields = ["team_id", "created_at", "updated_at"]

    @extend_schema_field(
        {
            "type": "object",
            "nullable": True,
            "properties": {
                "type": {"type": "string", "enum": ["user", "role"]},
                "id": {"oneOf": [{"type": "integer"}, {"type": "string", "format": "uuid"}]},
            },
        }
    )
    def get_assignee(self, obj):
        if obj.user_id:
            return {"type": "user", "id": obj.user_id}
        elif obj.role_id:
            return {"type": "role", "id": obj.role_id}
        return None


class ErrorTrackingAssignmentRuleViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet, RuleReorderingMixin):
    scope_object = "error_tracking"
    queryset = ErrorTrackingAssignmentRule.objects.order_by("order_key").all()
    serializer_class = ErrorTrackingAssignmentRuleSerializer

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team.id)

    def _apply_rule_update(self, request: ValidatedRequest) -> Response:
        assignment_rule = self.get_object()
        json_filters = request.validated_data.get("filters")
        assignee = request.validated_data.get("assignee")

        if json_filters:
            parsed_filters = PropertyGroupFilterValue(**json_filters)
            assignment_rule.filters = json_filters
            assignment_rule.bytecode = generate_byte_code(self.team, parsed_filters)

        if assignee:
            assignment_rule.user_id = None if assignee["type"] != "user" else assignee["id"]
            assignment_rule.role_id = None if assignee["type"] != "role" else assignee["id"]

        assignment_rule.disabled_data = None
        assignment_rule.save()

        posthoganalytics.capture(
            "error_tracking_assignment_rule_edited",
            groups=groups(self.team.organization, self.team),
        )

        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)

    @validated_request(
        request_serializer=ErrorTrackingAssignmentRuleUpdateRequestSerializer,
        responses={204: None},
    )
    def update(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        return self._apply_rule_update(request)

    @validated_request(
        request_serializer=ErrorTrackingAssignmentRuleUpdateRequestSerializer,
        responses={204: None},
    )
    def partial_update(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        return self._apply_rule_update(request)

    def destroy(self, request, *args, **kwargs) -> Response:
        response = super().destroy(request, *args, **kwargs)

        posthoganalytics.capture(
            "error_tracking_assignment_rule_deleted",
            groups=groups(self.team.organization, self.team),
        )

        return response

    @validated_request(
        request_serializer=ErrorTrackingAssignmentRuleCreateRequestSerializer,
        responses={201: OpenApiResponse(response=ErrorTrackingAssignmentRuleSerializer)},
    )
    def create(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        json_filters = request.validated_data["filters"]
        assignee = request.validated_data["assignee"]

        parsed_filters = PropertyGroupFilterValue(**json_filters)

        bytecode = generate_byte_code(self.team, parsed_filters)

        assignment_rule = ErrorTrackingAssignmentRule.objects.create(
            team=self.team,
            filters=json_filters,
            bytecode=bytecode,
            order_key=0,
            user_id=None if assignee["type"] != "user" else assignee["id"],
            role_id=None if assignee["type"] != "role" else assignee["id"],
        )

        posthoganalytics.capture(
            "error_tracking_assignment_rule_created",
            groups=groups(self.team.organization, self.team),
        )

        serializer = ErrorTrackingAssignmentRuleSerializer(assignment_rule)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
