from typing import override

import structlog
import posthoganalytics
from pydantic import ValidationError as PydanticValidationError
from rest_framework import serializers, status, viewsets
from rest_framework.response import Response

from posthog.schema import PropertyGroupFilterValue

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import groups
from posthog.models.team.team import Team

from products.error_tracking.backend.models import ErrorTrackingSuppressionRule

from .utils import RuleReorderingMixin, generate_byte_code, generate_match_all_bytecode

logger = structlog.get_logger(__name__)


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

        if json_filters is not None:
            if _has_filter_values(json_filters):
                try:
                    parsed_filters = PropertyGroupFilterValue(**json_filters)
                except (PydanticValidationError, TypeError):
                    return Response({"error": "Invalid filters"}, status=status.HTTP_400_BAD_REQUEST)
                suppression_rule.filters = json_filters
                suppression_rule.bytecode = generate_byte_code(self.team, parsed_filters)
            else:
                suppression_rule.filters = json_filters
                suppression_rule.bytecode = generate_match_all_bytecode()
        if "sampling_rate" in request.data:
            sampling_rate = request.data["sampling_rate"]
            if not isinstance(sampling_rate, (int, float)) or not (0.0 <= sampling_rate <= 1.0):
                return Response(
                    {"error": "sampling_rate must be a number between 0 and 1"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            suppression_rule.sampling_rate = sampling_rate
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

        if json_filters:
            if _has_filter_values(json_filters):
                try:
                    parsed_filters = PropertyGroupFilterValue(**json_filters)
                except (PydanticValidationError, TypeError):
                    return Response({"error": "Invalid filters"}, status=status.HTTP_400_BAD_REQUEST)
                bytecode = generate_byte_code(self.team, parsed_filters)
            elif "values" not in json_filters:
                return Response({"error": "Invalid filters"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                bytecode = generate_match_all_bytecode()
        else:
            json_filters = {"type": "AND", "values": []}
            bytecode = generate_match_all_bytecode()

        sampling_rate = request.data.get("sampling_rate", 1.0)
        if not isinstance(sampling_rate, (int, float)) or not (0.0 <= sampling_rate <= 1.0):
            return Response(
                {"error": "sampling_rate must be a number between 0 and 1"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        suppression_rule = ErrorTrackingSuppressionRule.objects.create(
            team=self.team,
            filters=json_filters,
            bytecode=bytecode,
            order_key=0,
            sampling_rate=sampling_rate,
        )

        posthoganalytics.capture(
            "error_tracking_suppression_rule_created",
            groups=groups(self.team.organization, self.team),
        )

        serializer = ErrorTrackingSuppressionRuleSerializer(suppression_rule)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


def _has_filter_values(json_filters: dict) -> bool:
    """Check whether a filter dict contains any actual filter values."""
    values = json_filters.get("values", [])
    if not values:
        return False
    # Check nested groups (the outer group wraps inner groups with actual filters)
    return any(v.get("values") or "key" in v for v in values)


NEGATIVE_OPERATORS = frozenset({"is_not", "not_regex", "not_icontains"})

# Properties that require server-side symbol resolution to have meaningful
# values. Client-side these will contain minified/bundled names.
SERVER_ONLY_PROPERTIES = frozenset({"$exception_sources", "$exception_functions"})


def _is_filter_client_safe(f: dict) -> bool:
    """Check whether a single filter entry can be evaluated client-side."""
    if f.get("key") in SERVER_ONLY_PROPERTIES:
        return False
    if f.get("operator") in NEGATIVE_OPERATORS:
        return False
    return True


def _get_client_safe_filters(filters: dict) -> dict | None:
    """Return a version of the filters suitable for client-side evaluation.

    - OR rules: strip server-only filters, keep client-safe ones. If any
      client-safe filter matches, the rule matches (short-circuit OR).
    - AND rules: all filters must be client-safe. If any is server-only,
      the entire group cannot be evaluated client-side.

    Returns None if no client-safe evaluation is possible.
    """
    values = filters.get("values", [])
    if not values:
        return filters

    filter_type = filters.get("type", "AND").upper()

    if filter_type == "OR":
        safe_values = []
        for value in values:
            if "key" in value:
                if _is_filter_client_safe(value):
                    safe_values.append(value)
            elif "values" in value:
                safe_group = _get_client_safe_filters(value)
                if safe_group is not None:
                    safe_values.append(safe_group)
        if not safe_values:
            return None
        return {**filters, "values": safe_values}
    else:
        # AND: every filter must be client-safe
        for value in values:
            if "key" in value:
                if not _is_filter_client_safe(value):
                    return None
            elif "values" in value:
                if _get_client_safe_filters(value) is None:
                    return None
        return filters


def get_client_safe_suppression_rules(team: Team) -> list[dict]:
    rules = list(ErrorTrackingSuppressionRule.objects.filter(team=team).values_list("filters", "sampling_rate"))
    result = []
    for filters, sampling_rate in rules:
        safe = _get_client_safe_filters(filters)
        if safe is not None:
            rule_data = {**safe}
            if sampling_rate < 1.0:
                rule_data["samplingRate"] = sampling_rate
            result.append(rule_data)
    return result
