from typing import Any, Protocol, TypeVar

import structlog
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from posthog.schema import PropertyGroupFilterValue

from posthog.hogql import ast
from posthog.hogql.compiler.bytecode import create_bytecode
from posthog.hogql.property import property_to_expr

from posthog.api.utils import action
from posthog.models.team.team import Team

from products.error_tracking.backend.hogvm_stl import RUST_HOGVM_STL
from products.error_tracking.backend.models import ErrorTrackingIssueAssignment

from common.hogvm.python.operation import Operation

logger = structlog.get_logger(__name__)


class ErrorTrackingIssueAssignmentSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    type = serializers.SerializerMethodField()

    class Meta:
        model = ErrorTrackingIssueAssignment
        fields = ["id", "type"]

    def get_id(self, obj):
        return obj.user_id if obj.user_id else str(obj.role_id) if obj.role_id else None

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


def generate_byte_code(team: Team, props: PropertyGroupFilterValue):
    expr = property_to_expr(props, team, strict=True)
    # The rust HogVM expects a return statement, so we wrap the compiled filter expression in one
    with_return = ast.ReturnStatement(expr=expr)
    bytecode = create_bytecode(with_return).bytecode
    validate_bytecode(bytecode)
    return bytecode


def validate_bytecode(bytecode: list[Any]) -> None:
    for i, op in enumerate(bytecode):
        if not isinstance(op, Operation):
            continue
        if op == Operation.CALL_GLOBAL:
            name = bytecode[i + 1]
            if not isinstance(name, str):
                raise ValidationError(f"Expected string for global function name, got {type(name)}")
            if name not in RUST_HOGVM_STL:
                raise ValidationError(f"Unknown global function: {name}")
