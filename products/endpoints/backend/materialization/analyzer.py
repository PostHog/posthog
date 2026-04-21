"""Main analyzer entry point: decides whether a query's variables can be materialized.

The top-level ``analyze_variables_for_materialization`` composes the 5 helpers below
into a linear pipeline. Each helper returns either a reject reason (string) or ``None``
to signal success. Pipeline short-circuits on the first reject reason.
"""

from typing import Any, Optional

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.exceptions_capture import capture_exception

from products.endpoints.backend.materialization.aggregates import extract_aggregate_name, get_reaggregation
from products.endpoints.backend.materialization.cte_propagation import (
    DownstreamCTEPlan,
    _build_cte_read_graph,
    _classify_downstream_cte,
    _downstream_ctes,
    _has_joins,
    _topological_order,
)
from products.endpoints.backend.materialization.range_buckets import _detect_range_variables
from products.endpoints.backend.materialization.types import (
    SUPPORTED_MATERIALIZATION_OPS,
    MaterializableVariable,
    VariableInHavingClauseError,
)
from products.endpoints.backend.materialization.variables import VariablePlaceholderFinder, find_all_variable_usages


def analyze_variables_for_materialization(
    hogql_query: dict[str, Any],
    bucket_overrides: dict[str, str] | None = None,
) -> tuple[bool, str, list[MaterializableVariable]]:
    """Check if query variables can be materialized.

    Each variable must be used in a WHERE clause with a supported operator
    (=, >=, >, <, <=). Multiple variables are supported.

    Returns (can_materialize, reason, variable_infos).
    """
    ast_node, reject = _parse_query_or_fail(hogql_query)
    if reject is not None:
        return False, reject, []
    assert ast_node is not None  # parse success implies non-None AST

    placeholders = _collect_variable_placeholders(ast_node)
    if not placeholders:
        return False, "No variables found", []

    variables_dict = hogql_query.get("variables", {})
    result_vars: list[MaterializableVariable] = []
    seen_code_names: set[str] = set()

    for placeholder in placeholders:
        var, reject = _build_materializable_variable(placeholder, ast_node, variables_dict, seen_code_names)
        if reject is not None:
            return False, reject, []
        if var is not None:
            result_vars.append(var)

    # Detect range variables and set bucket_fn for bucketed materialization.
    # Single-bound ranges (e.g., just >= start) are supported — we materialize all data
    # bucketed and filter at read time with the user's value.
    _detect_range_variables(result_vars, bucket_overrides=bucket_overrides)

    reject = _validate_reaggregation_for_range_vars(ast_node, result_vars)
    if reject is not None:
        return False, reject, []

    # Safety check: CTE variables + top-level JOINs produce wrong results.
    # Removing a CTE's WHERE changes its row cardinality, which changes JOIN
    # output. Filtering after materialization can't recover the original semantics
    # (e.g. LEFT JOIN non-matches get NULL for the variable column and are lost).
    has_cte_vars = any(v.cte_name is not None for v in result_vars)
    if has_cte_vars and isinstance(ast_node, ast.SelectQuery) and _has_joins(ast_node):
        return False, "CTE variables with JOINs in the top-level query are not supported for materialization", []

    reject = _build_downstream_plans(ast_node, result_vars)
    if reject is not None:
        return False, reject, []

    return True, "OK", result_vars


def _parse_query_or_fail(
    hogql_query: dict[str, Any],
) -> tuple[Optional[ast.SelectQuery | ast.SelectSetQuery], Optional[str]]:
    """Parse the HogQL query string.

    Returns ``(ast_node, None)`` on success or ``(None, reason)`` on failure.
    """
    query_str = hogql_query.get("query")
    if not query_str:
        return None, "No query string found"

    try:
        return parse_select(query_str), None
    except Exception as e:
        capture_exception(e)
        return None, "Failed to parse query."


def _collect_variable_placeholders(ast_node: ast.SelectQuery | ast.SelectSetQuery) -> list[ast.Placeholder]:
    """Find every ``{variables.X}`` placeholder referenced anywhere in the AST."""
    finder = VariablePlaceholderFinder()
    finder.visit(ast_node)
    return finder.variable_placeholders


def _build_materializable_variable(
    placeholder: ast.Placeholder,
    ast_node: ast.SelectQuery | ast.SelectSetQuery,
    variables_dict: dict[str, Any],
    seen_code_names: set[str],
) -> tuple[Optional[MaterializableVariable], Optional[str]]:
    """Validate a single placeholder and build a MaterializableVariable.

    Returns:
    - ``(var, None)``: variable built successfully (caller should append to result list)
    - ``(None, reject_reason)``: unrecoverable rejection — caller short-circuits
    - ``(None, None)``: placeholder was a duplicate of one already seen; skip silently

    ``seen_code_names`` is mutated in-place to deduplicate across calls.
    """
    if not placeholder.chain or len(placeholder.chain) < 2:
        return None, "Invalid variable placeholder format"

    code_name = str(placeholder.chain[1])
    if code_name in seen_code_names:
        return None, None
    seen_code_names.add(code_name)

    try:
        all_usages = find_all_variable_usages(ast_node, placeholder)
    except VariableInHavingClauseError:
        return None, "Variable used in HAVING clause are not supported for materialization."
    except ValueError as e:
        capture_exception(e)
        return None, "Invalid variable usage in WHERE clause."

    if not all_usages:
        return None, "Variable not used in WHERE clause"

    cte_names = {cte_name for cte_name, _ in all_usages}
    if len(cte_names) > 1:
        has_top_level = None in cte_names
        has_cte = any(n is not None for n in cte_names)
        if has_top_level and has_cte:
            return None, "Variable used in both CTE and top-level query is not yet supported"
        return None, "Variable used in multiple CTEs is not yet supported"

    cte_name = next(iter(cte_names))
    # All usages of the same variable should be consistent; the first is canonical.
    variable_usage = all_usages[0][1]

    if variable_usage.operator not in SUPPORTED_MATERIALIZATION_OPS:
        return None, f"Unsupported operator {variable_usage.operator}, supported: =, >=, >, <, <="

    variable_id = next(
        (var_id for var_id, var_data in variables_dict.items() if var_data.get("code_name") == code_name),
        None,
    )

    if not variable_id:
        return None, "Variable metadata not found"

    return (
        MaterializableVariable(
            variable_id=variable_id,
            code_name=code_name,
            column_chain=variable_usage.column_chain,
            column_expression=variable_usage.column_expression,
            operator=variable_usage.operator,
            column_ast=variable_usage.column_ast,
            value_wrapper_fns=variable_usage.value_wrapper_fns,
            cte_name=cte_name,
        ),
        None,
    )


def _validate_reaggregation_for_range_vars(
    ast_node: ast.SelectQuery | ast.SelectSetQuery,
    result_vars: list[MaterializableVariable],
) -> Optional[str]:
    """If any range variable has bucket_fn set, every top-level SELECT aggregate must be re-aggregatable."""
    has_range_vars = any(v.bucket_fn is not None for v in result_vars)
    if not has_range_vars:
        return None
    if not isinstance(ast_node, ast.SelectQuery) or not ast_node.select:
        return None
    for expr in ast_node.select:
        agg_name = extract_aggregate_name(expr)
        if agg_name and get_reaggregation(agg_name) is None:
            return f"Aggregate function '{agg_name}' cannot be re-aggregated for range variable materialization"
    return None


def _build_downstream_plans(
    ast_node: ast.SelectQuery | ast.SelectSetQuery,
    result_vars: list[MaterializableVariable],
) -> Optional[str]:
    """For each CTE-bound variable, classify downstream CTEs and attach a propagation plan.

    Mutates each var's ``downstream_plans`` in-place. Returns a reject reason at the
    first downstream CTE we can't safely propagate through; otherwise returns None.
    """
    has_cte_vars = any(v.cte_name is not None for v in result_vars)
    if not (has_cte_vars and isinstance(ast_node, ast.SelectQuery) and ast_node.ctes):
        return None

    graph = _build_cte_read_graph(ast_node)
    all_code_names = [v.code_name for v in result_vars if v.cte_name is not None]
    for var in result_vars:
        if var.cte_name is None:
            continue
        downstream = _downstream_ctes(graph, var.cte_name)
        propagating = downstream | {var.cte_name}
        plans: dict[str, DownstreamCTEPlan] = {}
        for d_cte_name in _topological_order(graph, downstream):
            d_cte = ast_node.ctes[d_cte_name]
            plan = _classify_downstream_cte(d_cte_name, d_cte.expr, propagating, all_code_names)
            if plan.reject_reason:
                return plan.reject_reason
            plans[d_cte_name] = plan
        var.downstream_plans = plans

    return None
