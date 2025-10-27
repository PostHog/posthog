import structlog
from rest_framework import serializers, status, viewsets
from rest_framework.response import Response

from posthog.schema import PropertyGroupFilterValue

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.models import ErrorTrackingGroupingRule

from .utils import RuleReorderingMixin, generate_byte_code

logger = structlog.get_logger(__name__)


class ErrorTrackingGroupingRuleSerializer(serializers.ModelSerializer):
    assignee = serializers.SerializerMethodField()

    class Meta:
        model = ErrorTrackingGroupingRule
        fields = ["id", "filters", "assignee", "order_key", "disabled_data"]
        read_only_fields = ["team_id"]

    def get_assignee(self, obj):
        if obj.user_id:
            return {"type": "user", "id": obj.user_id}
        elif obj.role_id:
            return {"type": "role", "id": obj.role_id}
        return None


class ErrorTrackingGroupingRuleViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet, RuleReorderingMixin):
    scope_object = "error_tracking"
    queryset = ErrorTrackingGroupingRule.objects.order_by("order_key").all()
    serializer_class = ErrorTrackingGroupingRuleSerializer

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team.id)

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

        grouping_rule.save()

        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)

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

        serializer = ErrorTrackingGroupingRuleSerializer(grouping_rule)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
