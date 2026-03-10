from typing import override

import structlog
import posthoganalytics
from rest_framework import serializers, status, viewsets
from rest_framework.response import Response

from posthog.schema import PropertyGroupFilterValue

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import groups
from posthog.models.team.team import Team

from products.error_tracking.backend.models import ErrorTrackingSuppressionRule

from .utils import RuleReorderingMixin, generate_byte_code

logger = structlog.get_logger(__name__)


class ErrorTrackingSuppressionRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingSuppressionRule
        fields = ["id", "filters", "order_key", "disabled_data", "created_at", "updated_at"]
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

        if json_filters:
            parsed_filters = PropertyGroupFilterValue(**json_filters)
            suppression_rule.filters = json_filters
            suppression_rule.bytecode = generate_byte_code(self.team, parsed_filters)

        suppression_rule.disabled_data = None
        suppression_rule.save()

        posthoganalytics.capture(
            "error_tracking_suppression_rule_edited",
            groups=groups(self.team.organization, self.team),
        )

        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)

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

        if not json_filters:
            return Response({"error": "Filters are required"}, status=status.HTTP_400_BAD_REQUEST)

        parsed_filters = PropertyGroupFilterValue(**json_filters)
        bytecode = generate_byte_code(self.team, parsed_filters)

        suppression_rule = ErrorTrackingSuppressionRule.objects.create(
            team=self.team,
            filters=json_filters,
            bytecode=bytecode,
            order_key=0,
        )

        posthoganalytics.capture(
            "error_tracking_suppression_rule_created",
            groups=groups(self.team.organization, self.team),
        )

        serializer = ErrorTrackingSuppressionRuleSerializer(suppression_rule)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


NEGATIVE_OPERATORS = frozenset({"is_not", "not_regex", "not_icontains"})


def _has_negative_operator(filters: dict) -> bool:
    """Check if a filter group contains any negative operator.

    Negative operators (is_not, not_regex, not_icontains) can produce false
    positives on unresolved exception data (e.g. minified types/values), so
    rules using them must only be evaluated server-side after symbol resolution.
    """
    for value in filters.get("values", []):
        if "operator" in value:
            if value["operator"] in NEGATIVE_OPERATORS:
                return True
        elif "values" in value:
            if _has_negative_operator(value):
                return True
    return False


def get_client_safe_suppression_rules(team: Team) -> list[dict]:
    rules = list(ErrorTrackingSuppressionRule.objects.filter(team=team).values_list("filters", flat=True))
    return [r for r in rules if not _has_negative_operator(r)]
