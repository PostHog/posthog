from typing import override

import structlog
from rest_framework import serializers, status, viewsets
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.team.team import Team

from products.error_tracking.backend.models import ErrorTrackingSuppressionRule

from .utils import RuleReorderingMixin

logger = structlog.get_logger(__name__)


class ErrorTrackingSuppressionRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingSuppressionRule
        fields = ["id", "filters", "order_key"]
        read_only_fields = ["team_id"]


class ErrorTrackingSuppressionRuleViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet, RuleReorderingMixin):
    scope_object = "error_tracking"
    queryset = ErrorTrackingSuppressionRule.objects.order_by("order_key").all()
    serializer_class = ErrorTrackingSuppressionRuleSerializer

    @override
    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team.id)

    @override
    def update(self, request, *args, **kwargs) -> Response:
        suppression_rule = self.get_object()
        filters = request.data.get("filters")

        if filters:
            suppression_rule.filters = filters

        suppression_rule.save()

        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)

    @override
    def create(self, request, *args, **kwargs) -> Response:
        filters = request.data.get("filters")

        if not filters:
            return Response({"error": "Filters are required"}, status=status.HTTP_400_BAD_REQUEST)

        suppression_rule = ErrorTrackingSuppressionRule.objects.create(
            team=self.team,
            filters=filters,
            order_key=0,
        )

        serializer = ErrorTrackingSuppressionRuleSerializer(suppression_rule)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


def get_suppression_rules(team: Team):
    return list(ErrorTrackingSuppressionRule.objects.filter(team=team).values_list("filters", flat=True))
