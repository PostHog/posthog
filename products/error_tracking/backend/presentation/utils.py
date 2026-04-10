from typing import Protocol, TypeVar

import structlog
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers, status
from rest_framework.response import Response

from posthog.api.utils import action

from products.error_tracking.backend.models import ErrorTrackingIssueAssignment
from products.error_tracking.backend.rule_bytecode import generate_byte_code, generate_match_all_bytecode

logger = structlog.get_logger(__name__)

__all__ = [
    "ErrorTrackingIssueAssignmentSerializer",
    "RuleReorderingMixin",
    "generate_byte_code",
    "generate_match_all_bytecode",
]


class ErrorTrackingIssueAssignmentSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    type = serializers.SerializerMethodField()

    class Meta:
        model = ErrorTrackingIssueAssignment
        fields = ["id", "type"]

    @extend_schema_field({"oneOf": [{"type": "integer"}, {"type": "string"}], "nullable": True})
    def get_id(self, obj):
        return obj.user_id if obj.user_id else str(obj.role_id) if obj.role_id else None

    @extend_schema_field(serializers.CharField())
    def get_type(self, obj):
        return "role" if obj.role else "user"


class HasGetQueryset(Protocol):
    def get_queryset(self): ...


T = TypeVar("T", bound=HasGetQueryset)


class RuleReorderingMixin:
    @action(methods=["PATCH"], detail=False)
    def reorder(self: T, request, **kwargs):
        orders: dict[str, int] = request.data.get("orders", {})
        rules = self.get_queryset().filter(id__in=orders.keys())

        for rule in rules:
            rule.order_key = orders[str(rule.id)]

        self.get_queryset().bulk_update(rules, ["order_key"])

        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)
