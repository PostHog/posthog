from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from django.core.exceptions import ValidationError as DjangoValidationError

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from posthog.hogql import ast
from posthog.hogql.compiler.bytecode import create_bytecode
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_program
from posthog.hogql.visitor import TraversingVisitor

from common.hogvm.python.stl import STL

DEFAULT_SCORING_SOURCE = Path(__file__).with_name("scoring_formula.hog").read_text()
SCORING_GLOBALS = frozenset({"company", "signup", "enrichments", "lists"})
MAX_SCORING_SOURCE_LENGTH = 30_000
DISALLOWED_FUNCTIONS = frozenset(name for name, function in STL.items() if function.is_blocking) | {
    "sql",
    "now",
    "today",
    "randomFloat",
    "generateUUIDv4",
}


class _ValidateFormula(TraversingVisitor):
    def visit_call(self, node: ast.Call) -> None:
        if node.name in DISALLOWED_FUNCTIONS:
            raise ValueError(f"Function {node.name} is not allowed in a scoring formula")
        super().visit_call(node)

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        raise ValueError("Queries are not allowed in a scoring formula")

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        raise ValueError("Queries are not allowed in a scoring formula")


@lru_cache(maxsize=64)
def compile_scoring_formula(source: str) -> list[Any]:
    try:
        if not source.strip() or len(source) > MAX_SCORING_SOURCE_LENGTH:
            raise ValueError(f"Scoring source must contain 1 to {MAX_SCORING_SOURCE_LENGTH} characters")
        program = parse_program(source)
        _ValidateFormula().visit(program)
        context = HogQLContext(team_id=None, globals=dict.fromkeys(SCORING_GLOBALS))
        bytecode = create_bytecode(program, context=context).bytecode
        notices = context.errors + context.warnings
        if notices:
            raise ValueError("; ".join(notice.message for notice in notices))
        return bytecode
    except Exception as error:
        raise ValueError(f"Invalid scoring formula: {error}") from error


class ScoringRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)

    source: Annotated[str, Field(strict=True, min_length=1, max_length=MAX_SCORING_SOURCE_LENGTH)] = (
        DEFAULT_SCORING_SOURCE
    )

    @field_validator("source")
    @classmethod
    def valid_formula(cls, value: str) -> str:
        compile_scoring_formula(value)
        return value


def parse_scoring_rules(value: dict[str, Any]) -> ScoringRules:
    return ScoringRules.model_validate(value)


def default_scoring_rules() -> dict[str, Any]:
    return ScoringRules().model_dump(mode="json")


def validate_scoring_rules(value: Any) -> None:
    try:
        parse_scoring_rules(value)
    except ValidationError as error:
        raise DjangoValidationError(
            [
                f"{'.'.join(str(part) for part in item['loc']) or 'scoring_rules'}: {item['msg']}"
                for item in error.errors()
            ]
        ) from error
