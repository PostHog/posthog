from typing import override

import structlog
import posthoganalytics
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import groups

from products.error_tracking.backend.logic import ErrorTrackingSuppressionRuleService
from products.error_tracking.backend.models import ErrorTrackingSuppressionRule

from .utils import RuleReorderingMixin

logger = structlog.get_logger(__name__)

__all__ = [
    "ErrorTrackingSuppressionRuleSerializer",
    "ErrorTrackingSuppressionRuleViewSet",
    "get_client_safe_suppression_rules",
]


class ErrorTrackingSuppressionRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingSuppressionRule
        fields = ["id", "filters", "order_key", "disabled_data", "sampling_rate", "created_at", "updated_at"]
        read_only_fields = ["team_id", "created_at", "updated_at"]


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
        json_filters = request.data.get("filters")

        try:
            ErrorTrackingSuppressionRuleService.update_rule(
                suppression_rule=suppression_rule,
                team=self.team,
                json_filters=json_filters,
                sampling_rate=request.data.get("sampling_rate") if "sampling_rate" in request.data else None,
            )
        except ValidationError as err:
            error = err.detail[0] if isinstance(err.detail, list) and err.detail else err.detail
            return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)

    @override
    def partial_update(self, request, *args, **kwargs) -> Response:
        return self.update(request, *args, **kwargs)

    @override
    def destroy(self, request, *args, **kwargs) -> Response:
        response = super().destroy(request, *args, **kwargs)

        posthoganalytics.capture(
            "error_tracking_suppression_rule_deleted",
            groups=groups(self.team.organization, self.team),
        )

        return response

    @override
    def create(self, request, *args, **kwargs) -> Response:
        json_filters = request.data.get("filters")

        try:
            suppression_rule = ErrorTrackingSuppressionRuleService.create_rule(
                team=self.team,
                json_filters=json_filters,
                sampling_rate=request.data.get("sampling_rate", 1.0),
            )
        except ValidationError as err:
            error = err.detail[0] if isinstance(err.detail, list) and err.detail else err.detail
            return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = ErrorTrackingSuppressionRuleSerializer(suppression_rule)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


def get_client_safe_suppression_rules(team):
    from products.error_tracking.backend.logic import get_client_safe_suppression_rules as get_logic_rules

    return get_logic_rules(team)
