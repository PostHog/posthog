from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from posthog.hogql import ast

if TYPE_CHECKING:
    from products.endpoints.backend.materialization.cte_propagation import DownstreamCTEPlan


class VariableInHavingClauseError(ValueError):
    """Raised when a variable is used in a HAVING clause, which is not supported for materialization."""


@dataclass
class MaterializableVariable:
    """Info about a variable that can be materialized"""

    variable_id: str
    code_name: str
    column_chain: list[str]
    column_expression: str
    operator: ast.CompareOperationOp = ast.CompareOperationOp.Eq
    column_ast: Optional[ast.Expr] = None
    value_wrapper_fns: Optional[list[str]] = None
    cte_name: Optional[str] = None  # CTE containing the variable; None = top-level query

    bucket_fn: Optional[str] = None  # e.g. "toStartOfDay" for range variables on timestamp

    # Keyed by downstream CTE name. Populated by the analyzer; consumed by the transformer.
    downstream_plans: dict[str, DownstreamCTEPlan] = field(default_factory=dict)


@dataclass
class VariableUsageInWhere:
    """Details of how a variable is used in a WHERE clause"""

    column_chain: list[str]
    column_expression: str
    operator: ast.CompareOperationOp
    column_ast: Optional[ast.Expr] = None
    value_wrapper_fns: Optional[list[str]] = None


SUPPORTED_MATERIALIZATION_OPS = frozenset(
    {
        ast.CompareOperationOp.Eq,
        ast.CompareOperationOp.GtEq,
        ast.CompareOperationOp.Gt,
        ast.CompareOperationOp.Lt,
        ast.CompareOperationOp.LtEq,
        ast.CompareOperationOp.Like,
        ast.CompareOperationOp.ILike,
        ast.CompareOperationOp.NotLike,
        ast.CompareOperationOp.NotILike,
    }
)
