from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Optional

from posthog.hogql import ast

if TYPE_CHECKING:
    from products.endpoints.backend.materialization.cte_propagation import DownstreamCTEPlan


class VariableInHavingClauseError(ValueError):
    """Raised when a variable is used in a HAVING clause, which is not supported for materialization."""


class RejectionCode(Enum):
    """Stable identifiers for every reason a query (or a variable within it) cannot be materialized.

    Tests, telemetry, and API callers assert on codes; the human-readable message lives on the
    ``Rejection`` instance and can be reworded without breaking them.
    """

    # Query-level (models.can_materialize)
    QUERY_TYPE_NOT_MATERIALIZABLE = "query_type_not_materializable"
    COMPARE_MODE_NOT_SUPPORTED = "compare_mode_not_supported"
    COHORT_BREAKDOWN_NOT_SUPPORTED = "cohort_breakdown_not_supported"
    EMPTY_OR_INVALID_QUERY = "empty_or_invalid_query"
    VARIABLES_NOT_SUPPORTED = "variables_not_supported"  # wraps an analyzer rejection

    # Parse / placeholder
    NO_QUERY_STRING = "no_query_string"
    PARSE_FAILED = "parse_failed"
    NO_VARIABLES = "no_variables"
    INVALID_PLACEHOLDER_FORMAT = "invalid_placeholder_format"
    VARIABLE_METADATA_NOT_FOUND = "variable_metadata_not_found"

    # WHERE / HAVING usage
    VARIABLE_NOT_IN_WHERE = "variable_not_in_where"
    VARIABLE_IN_HAVING = "variable_in_having"
    INVALID_WHERE_USAGE = "invalid_where_usage"
    UNSUPPORTED_OPERATOR = "unsupported_operator"

    # CTE placement
    VARIABLE_IN_CTE_AND_TOP_LEVEL = "variable_in_cte_and_top_level"
    VARIABLE_IN_MULTIPLE_CTES = "variable_in_multiple_ctes"
    CTE_VARIABLE_WITH_TOP_LEVEL_JOIN = "cte_variable_with_top_level_join"

    # Range bucketing
    AGGREGATE_NOT_REAGGREGATABLE = "aggregate_not_reaggregatable"

    # Downstream CTE propagation
    DOWNSTREAM_UNSUPPORTED_BODY = "downstream_unsupported_body"
    DOWNSTREAM_WINDOW_FUNCTION = "downstream_window_function"
    DOWNSTREAM_UNSAFE_JOIN = "downstream_unsafe_join"
    DOWNSTREAM_NESTED_SUBQUERY_REF = "downstream_nested_subquery_ref"
    DOWNSTREAM_NO_PROPAGATING_SOURCE = "downstream_no_propagating_source"
    DOWNSTREAM_CODE_NAME_COLLISION = "downstream_code_name_collision"

    # UNION leg (within a downstream CTE)
    UNION_NOT_ALL = "union_not_all"
    UNION_LEG_FAILED = "union_leg_failed"  # wraps an inner rejection from a leg
    UNION_LEG_NESTED_SET_QUERY = "union_leg_nested_set_query"
    UNION_LEG_NO_PROPAGATING_SOURCE = "union_leg_no_propagating_source"


@dataclass(frozen=True)
class Rejection:
    """Why something can't be materialized. ``code`` is stable; ``message`` is user-facing."""

    code: RejectionCode
    message: str
    # Populated only for wrapper codes (VARIABLES_NOT_SUPPORTED, UNION_LEG_FAILED) so callers
    # can drill down to the underlying cause without substring-parsing the message.
    caused_by: Optional[Rejection] = None

    # --- Query-level ---

    @classmethod
    def query_type_not_materializable(cls, query_kind: Optional[str], supported: list[str]) -> Rejection:
        supported_str = ", ".join(sorted(supported))
        return cls(
            RejectionCode.QUERY_TYPE_NOT_MATERIALIZABLE,
            f"Query type '{query_kind}' cannot be materialized. Supported types: {supported_str}",
        )

    @classmethod
    def compare_mode_not_supported(cls) -> Rejection:
        return cls(
            RejectionCode.COMPARE_MODE_NOT_SUPPORTED,
            "Compare mode is not supported for materialized endpoints.",
        )

    @classmethod
    def cohort_breakdown_not_supported(cls) -> Rejection:
        return cls(
            RejectionCode.COHORT_BREAKDOWN_NOT_SUPPORTED,
            "Cohort breakdowns are not supported for materialized endpoints.",
        )

    @classmethod
    def empty_or_invalid_query(cls) -> Rejection:
        return cls(RejectionCode.EMPTY_OR_INVALID_QUERY, "Query is empty or invalid.")

    @classmethod
    def variables_not_supported(cls, inner: Rejection) -> Rejection:
        return cls(
            RejectionCode.VARIABLES_NOT_SUPPORTED,
            f"Variables not supported: {inner.message}",
            caused_by=inner,
        )

    # --- Parse / placeholder ---

    @classmethod
    def no_query_string(cls) -> Rejection:
        return cls(RejectionCode.NO_QUERY_STRING, "No query string found")

    @classmethod
    def parse_failed(cls) -> Rejection:
        return cls(RejectionCode.PARSE_FAILED, "Failed to parse query.")

    @classmethod
    def no_variables(cls) -> Rejection:
        return cls(RejectionCode.NO_VARIABLES, "No variables found")

    @classmethod
    def invalid_placeholder_format(cls) -> Rejection:
        return cls(RejectionCode.INVALID_PLACEHOLDER_FORMAT, "Invalid variable placeholder format")

    @classmethod
    def variable_metadata_not_found(cls) -> Rejection:
        return cls(RejectionCode.VARIABLE_METADATA_NOT_FOUND, "Variable metadata not found")

    # --- WHERE / HAVING ---

    @classmethod
    def variable_not_in_where(cls) -> Rejection:
        return cls(RejectionCode.VARIABLE_NOT_IN_WHERE, "Variable not used in WHERE clause")

    @classmethod
    def variable_in_having(cls) -> Rejection:
        return cls(
            RejectionCode.VARIABLE_IN_HAVING,
            "Variable used in HAVING clause is not supported for materialization.",
        )

    @classmethod
    def invalid_where_usage(cls) -> Rejection:
        return cls(RejectionCode.INVALID_WHERE_USAGE, "Invalid variable usage in WHERE clause.")

    @classmethod
    def unsupported_operator(cls, op: ast.CompareOperationOp) -> Rejection:
        return cls(
            RejectionCode.UNSUPPORTED_OPERATOR,
            f"Unsupported operator {op}, supported: =, >=, >, <, <=, LIKE, ILIKE, NOT LIKE, NOT ILIKE",
        )

    # --- CTE placement ---

    @classmethod
    def variable_in_cte_and_top_level(cls) -> Rejection:
        return cls(
            RejectionCode.VARIABLE_IN_CTE_AND_TOP_LEVEL,
            "Variable used in both CTE and top-level query is not yet supported",
        )

    @classmethod
    def variable_in_multiple_ctes(cls) -> Rejection:
        return cls(
            RejectionCode.VARIABLE_IN_MULTIPLE_CTES,
            "Variable used in multiple CTEs is not yet supported",
        )

    @classmethod
    def cte_variable_with_top_level_join(cls) -> Rejection:
        return cls(
            RejectionCode.CTE_VARIABLE_WITH_TOP_LEVEL_JOIN,
            "CTE variables with JOINs in the top-level query are not supported for materialization",
        )

    # --- Range bucketing ---

    @classmethod
    def aggregate_not_reaggregatable(cls, agg_name: str) -> Rejection:
        return cls(
            RejectionCode.AGGREGATE_NOT_REAGGREGATABLE,
            f"Aggregate function '{agg_name}' cannot be re-aggregated for range variable materialization",
        )

    # --- Downstream CTE propagation ---

    @classmethod
    def downstream_unsupported_body(cls, type_name: str) -> Rejection:
        return cls(
            RejectionCode.DOWNSTREAM_UNSUPPORTED_BODY,
            f"Unsupported CTE body type: {type_name}",
        )

    @classmethod
    def downstream_window_function(cls) -> Rejection:
        return cls(
            RejectionCode.DOWNSTREAM_WINDOW_FUNCTION,
            "Window functions in downstream CTEs of a variable CTE are not yet supported for materialization",
        )

    @classmethod
    def downstream_unsafe_join(cls, join_type: Optional[str]) -> Rejection:
        return cls(
            RejectionCode.DOWNSTREAM_UNSAFE_JOIN,
            (
                "CTE variable propagation requires CROSS/INNER joins between propagating CTEs; "
                f"{join_type} not supported"
            ),
        )

    @classmethod
    def downstream_nested_subquery_ref(cls) -> Rejection:
        return cls(
            RejectionCode.DOWNSTREAM_NESTED_SUBQUERY_REF,
            "CTE variable propagation requires top-level FROM references; nested subquery reference not supported",
        )

    @classmethod
    def downstream_no_propagating_source(cls) -> Rejection:
        return cls(
            RejectionCode.DOWNSTREAM_NO_PROPAGATING_SOURCE,
            "Downstream CTE does not read from any propagating CTE",
        )

    @classmethod
    def downstream_code_name_collision(cls, code_name: str, cte_name: str) -> Rejection:
        return cls(
            RejectionCode.DOWNSTREAM_CODE_NAME_COLLISION,
            f"Variable code_name '{code_name}' collides with existing column in downstream CTE {cte_name}",
        )

    # --- UNION leg ---

    @classmethod
    def union_not_all(cls) -> Rejection:
        return cls(
            RejectionCode.UNION_NOT_ALL,
            "Only UNION ALL is supported for propagation across set operations",
        )

    @classmethod
    def union_leg_failed(cls, inner: Rejection) -> Rejection:
        return cls(
            RejectionCode.UNION_LEG_FAILED,
            f"Variable propagation failed on UNION leg: {inner.message}",
            caused_by=inner,
        )

    @classmethod
    def union_leg_nested_set_query(cls) -> Rejection:
        return cls(
            RejectionCode.UNION_LEG_NESTED_SET_QUERY,
            "Variable propagation failed on UNION leg: nested set queries are not supported",
        )

    @classmethod
    def union_leg_no_propagating_source(cls) -> Rejection:
        return cls(
            RejectionCode.UNION_LEG_NO_PROPAGATING_SOURCE,
            "Variable propagation failed on UNION leg: leg has no propagating CTE source",
        )


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
