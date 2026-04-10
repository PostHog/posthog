from typing import Any

from rest_framework.exceptions import ValidationError

from posthog.schema import PropertyGroupFilterValue

from posthog.hogql import ast
from posthog.hogql.compiler.bytecode import create_bytecode
from posthog.hogql.property import property_to_expr

from products.error_tracking.backend.hogvm_stl import RUST_HOGVM_STL

from common.hogvm.python.operation import Operation


def generate_byte_code(team, props: PropertyGroupFilterValue) -> list[Any]:
    expr = property_to_expr(props, team, strict=True)
    with_return = ast.ReturnStatement(expr=expr)
    bytecode = create_bytecode(with_return).bytecode
    validate_bytecode(bytecode)
    return bytecode


def generate_match_all_bytecode() -> list[Any]:
    with_return = ast.ReturnStatement(expr=ast.Constant(value=True))
    return create_bytecode(with_return).bytecode


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
