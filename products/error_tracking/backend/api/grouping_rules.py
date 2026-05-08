from typing import Optional
from uuid import UUID

import structlog
import posthoganalytics
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field, extend_schema_serializer
from pydantic import ValidationError as PydanticValidationError
from rest_framework import serializers, status, viewsets
from rest_framework.response import Response

from posthog.schema import PropertyGroupFilterValue

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import groups

from products.error_tracking.backend.models import ErrorTrackingGroupingRule, ErrorTrackingIssueFingerprintV2

from .utils import RuleReorderingMixin, generate_byte_code

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


class ErrorTrackingGroupingRuleSerializer(serializers.ModelSerializer):
    assignee = serializers.SerializerMethodField()
    issue = serializers.SerializerMethodField()

    class Meta:
        model = ErrorTrackingGroupingRule
        fields = [
            "id",
            "filters",
            "assignee",
            "description",
            "issue",
            "order_key",
            "disabled_data",
            "created_at",
            "updated_at",
        ]
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

    @extend_schema_field(
        serializers.DictField(child=serializers.CharField(), allow_null=True, help_text="Issue linked to this rule")
    )
    def get_issue(self, obj) -> Optional[dict]:
        issue_map = self.context.get("issue_map", {})
        issue = issue_map.get(str(obj.id))
        if issue:
            return {"id": str(issue.id), "name": issue.name}
        return None


@extend_schema_serializer(many=False)
class ErrorTrackingGroupingRuleListResponseSerializer(serializers.Serializer):
    results = ErrorTrackingGroupingRuleSerializer(many=True)


def _build_issue_map(team_id: int, rule_ids: list[str]) -> dict:
    """Build a mapping of rule_id -> ErrorTrackingIssue for grouping rules."""
    if not rule_ids:
        return {}
    fingerprints = (
        ErrorTrackingIssueFingerprintV2.objects.select_related("issue")
        .filter(
            team_id=team_id,
            fingerprint__in=[f"custom-rule:{rid}" for rid in rule_ids],
        )
        .only("fingerprint", "issue_id", "issue__id", "issue__name")
    )
    return {fp.fingerprint.removeprefix("custom-rule:"): fp.issue for fp in fingerprints}


class ErrorTrackingGroupingRuleViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet, RuleReorderingMixin):
    scope_object = "error_tracking"
    queryset = ErrorTrackingGroupingRule.objects.order_by("order_key").all()
    serializer_class = ErrorTrackingGroupingRuleSerializer
    pagination_class = None

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team.id)

    @extend_schema(responses={200: OpenApiResponse(response=ErrorTrackingGroupingRuleListResponseSerializer)})
    def list(self, request, *args, **kwargs) -> Response:
        queryset = list(self.filter_queryset(self.get_queryset()))
        rule_ids = [str(r.id) for r in queryset]
        issue_map = _build_issue_map(self.team.id, rule_ids)
        context = {**self.get_serializer_context(), "issue_map": issue_map}
        serializer = self.get_serializer(queryset, many=True, context=context)
        return Response({"results": serializer.data})

    def update(self, request, *args, **kwargs) -> Response:
        grouping_rule = self.get_object()
        assignee = request.data.get("assignee")
        json_filters = request.data.get("filters")
        description = request.data.get("description")

        if json_filters:
            parsed_filters = PropertyGroupFilterValue(**json_filters)
            grouping_rule.filters = json_filters
            grouping_rule.bytecode = generate_byte_code(self.team, parsed_filters)

        if assignee:
            grouping_rule.user_id = None if assignee["type"] != "user" else assignee["id"]
            grouping_rule.role_id = None if assignee["type"] != "role" else assignee["id"]

        if description:
            grouping_rule.description = description

        grouping_rule.disabled_data = None
        grouping_rule.save()

        posthoganalytics.capture(
            "error_tracking_grouping_rule_edited",
            groups=groups(self.team.organization, self.team),
        )

        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)

    def partial_update(self, request, *args, **kwargs) -> Response:
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs) -> Response:
        response = super().destroy(request, *args, **kwargs)

        posthoganalytics.capture(
            "error_tracking_grouping_rule_deleted",
            groups=groups(self.team.organization, self.team),
        )

        return response

    @validated_request(
        request_serializer=ErrorTrackingGroupingRuleCreateRequestSerializer,
        responses={201: OpenApiResponse(response=ErrorTrackingGroupingRuleSerializer)},
    )
    def create(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        json_filters = request.validated_data["filters"]
        assignee = request.validated_data.get("assignee")
        description = request.validated_data.get("description")

        parsed_filters = PropertyGroupFilterValue(**json_filters)
        bytecode = generate_byte_code(self.team, parsed_filters)

        grouping_rule = ErrorTrackingGroupingRule.objects.create(
            team=self.team,
            filters=json_filters,
            bytecode=bytecode,
            order_key=0,
            user_id=None if (not assignee or assignee["type"] != "user") else assignee["id"],
            role_id=None if (not assignee or assignee["type"] != "role") else assignee["id"],
            description=description,
        )

        posthoganalytics.capture(
            "error_tracking_grouping_rule_created",
            groups=groups(self.team.organization, self.team),
        )

        serializer = ErrorTrackingGroupingRuleSerializer(grouping_rule)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
