from typing import Optional
from uuid import UUID

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

logger = structlog.get_logger(__name__)


@extend_schema_field(PropertyGroupFilterValue)  # type: ignore[arg-type]
class ErrorTrackingGroupingRuleFiltersField(serializers.JSONField):
    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if not isinstance(value, dict):
            raise serializers.ValidationError("Expected a JSON object.")
        try:
            PropertyGroupFilterValue(**value)
        except PydanticValidationError as err:
            logger.warning("Invalid grouping rule filters payload", exc_info=err)
            raise serializers.ValidationError("Invalid filters payload.") from err
        if not error_tracking_api.has_filter_values(value):
            raise serializers.ValidationError("Filters must contain at least one filter value.")
        return value


@extend_schema_field({"oneOf": [{"type": "integer"}, {"type": "string", "format": "uuid"}]})
class ErrorTrackingGroupingRuleAssigneeIdField(serializers.Field):
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


class ErrorTrackingGroupingRuleAssigneeRequestSerializer(serializers.Serializer):
    type = serializers.ChoiceField(
        choices=["user", "role"],
        help_text="Assignee type. Use `user` for a user ID or `role` for a role UUID.",
    )
    id = ErrorTrackingGroupingRuleAssigneeIdField(
        help_text="User ID when `type` is `user`, or role UUID when `type` is `role`."
    )

    def validate(self, attrs):
        assignee_id = attrs["id"]
        if attrs["type"] == "user" and not isinstance(assignee_id, int):
            raise serializers.ValidationError({"id": "User assignee IDs must be integers."})
        if attrs["type"] == "role" and not isinstance(assignee_id, UUID):
            raise serializers.ValidationError({"id": "Role assignee IDs must be UUIDs."})
        return attrs


class ErrorTrackingGroupingRuleCreateRequestSerializer(serializers.Serializer):
    filters = ErrorTrackingGroupingRuleFiltersField(
        help_text="Property-group filters that define which exceptions should be grouped into the same issue."
    )
    assignee = ErrorTrackingGroupingRuleAssigneeRequestSerializer(
        required=False,
        allow_null=True,
        help_text="Optional user or role to assign to issues created by this grouping rule.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Optional human-readable description of what this grouping rule is for.",
    )


class ErrorTrackingGroupingRuleUpdateRequestSerializer(serializers.Serializer):
    filters = ErrorTrackingGroupingRuleFiltersField(
        required=False,
        allow_null=True,
        help_text="Property-group filters that define which exceptions should be grouped into the same issue. Omit to preserve the existing filters.",
    )


class ErrorTrackingGroupingRuleSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    filters = serializers.JSONField()
    assignee = serializers.SerializerMethodField()
    description = serializers.CharField(allow_null=True, allow_blank=True)
    issue = serializers.SerializerMethodField()
    order_key = serializers.IntegerField()
    disabled_data = serializers.JSONField(allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

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
        if obj.assignee is None:
            return None
        return {"type": obj.assignee.type, "id": obj.assignee.id}

    @extend_schema_field(
        serializers.DictField(child=serializers.CharField(), allow_null=True, help_text="Issue linked to this rule")
    )
    def get_issue(self, obj) -> Optional[dict]:
        if obj.issue is None:
            return None
        return {"id": str(obj.issue.id), "name": obj.issue.name}


@extend_schema_serializer(many=False)
class ErrorTrackingGroupingRuleListResponseSerializer(serializers.Serializer):
    results = ErrorTrackingGroupingRuleSerializer(many=True)


class ErrorTrackingGroupingRuleViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "error_tracking"
    serializer_class = ErrorTrackingGroupingRuleSerializer
    # The list endpoint returns all rules unpaginated ({"results": [...]}); without this the
    # default paginator makes the schema advertise limit/offset params the view doesn't honor.
    pagination_class = None

    @extend_schema(responses={200: OpenApiResponse(response=ErrorTrackingGroupingRuleListResponseSerializer)})
    def list(self, request, *args, **kwargs) -> Response:
        rules = error_tracking_api.list_grouping_rules(self.team.id)
        return Response({"results": self.get_serializer(rules, many=True).data})

    def retrieve(self, request, *args, pk=None, **kwargs) -> Response:
        rule = error_tracking_api.get_grouping_rule(self.team.id, pk)
        if rule is None:
            raise NotFound()
        return Response(self.get_serializer(rule).data)

    def _apply_rule_update(self, request: ValidatedRequest, pk: str) -> Response:
        try:
            rule = error_tracking_api.update_grouping_rule(
                self.team.id, pk, filters=request.validated_data.get("filters")
            )
        except error_tracking_api.InvalidBytecodeError as err:
            raise ValidationError(str(err)) from err
        if rule is None:
            raise NotFound()
        posthoganalytics.capture(
            "error_tracking_grouping_rule_edited",
            groups=groups(self.team.organization, self.team),
        )
        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)

    @validated_request(
        request_serializer=ErrorTrackingGroupingRuleUpdateRequestSerializer,
        responses={204: None},
    )
    def update(self, request: ValidatedRequest, *args, pk=None, **kwargs) -> Response:
        return self._apply_rule_update(request, pk)

    @validated_request(
        request_serializer=ErrorTrackingGroupingRuleUpdateRequestSerializer,
        responses={204: None},
    )
    def partial_update(self, request: ValidatedRequest, *args, pk=None, **kwargs) -> Response:
        return self._apply_rule_update(request, pk)

    def destroy(self, request, *args, pk=None, **kwargs) -> Response:
        if not error_tracking_api.delete_grouping_rule(self.team.id, pk):
            raise NotFound()
        posthoganalytics.capture(
            "error_tracking_grouping_rule_deleted",
            groups=groups(self.team.organization, self.team),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @validated_request(
        request_serializer=ErrorTrackingGroupingRuleCreateRequestSerializer,
        responses={201: OpenApiResponse(response=ErrorTrackingGroupingRuleSerializer)},
    )
    def create(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        try:
            rule = error_tracking_api.create_grouping_rule(
                self.team.id,
                filters=request.validated_data["filters"],
                assignee=request.validated_data.get("assignee"),
                description=request.validated_data.get("description"),
            )
        except error_tracking_api.InvalidBytecodeError as err:
            raise ValidationError(str(err)) from err
        posthoganalytics.capture(
            "error_tracking_grouping_rule_created",
            groups=groups(self.team.organization, self.team),
        )
        return Response(self.get_serializer(rule).data, status=status.HTTP_201_CREATED)

    @action(methods=["PATCH"], detail=False)
    def reorder(self, request, **kwargs) -> Response:
        orders: dict[str, int] = request.data.get("orders", {})
        error_tracking_api.reorder_grouping_rules(self.team.id, orders)
        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)
