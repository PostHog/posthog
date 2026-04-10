from typing import Optional

import structlog
import posthoganalytics
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers, status, viewsets
from rest_framework.response import Response

from posthog.schema import PropertyGroupFilterValue

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import groups

from products.error_tracking.backend.models import ErrorTrackingGroupingRule, ErrorTrackingIssueFingerprintV2

from .utils import RuleReorderingMixin, generate_byte_code

logger = structlog.get_logger(__name__)


class ErrorTrackingGroupingRuleSerializer(serializers.ModelSerializer):
    assignee = serializers.SerializerMethodField()
    issue = serializers.SerializerMethodField()

    class Meta:
        model = ErrorTrackingGroupingRule
        fields = ["id", "filters", "assignee", "issue", "order_key", "disabled_data", "created_at", "updated_at"]
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

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team.id)

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

    def create(self, request, *args, **kwargs) -> Response:
        json_filters = request.data.get("filters")
        assignee = request.data.get("assignee", None)
        description = request.data.get("description", None)

        if not json_filters:
            return Response({"error": "Filters are required"}, status=status.HTTP_400_BAD_REQUEST)

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
