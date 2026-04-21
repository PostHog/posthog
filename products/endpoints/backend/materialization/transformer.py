"""AST transformer that removes variable WHERE clauses and adds columns to SELECT and GROUP BY.

``MaterializationTransformer`` walks a parsed query and:

- Removes WHERE clauses referencing ``{variables.*}`` placeholders
- Adds one aliased column per variable to SELECT (aliased by ``code_name``)
- Updates GROUP BY (deduplicated by column chain) when the query aggregates
- CTE-aware: handles variables that live in a CTE, propagating the column through
  downstream CTEs via ``apply_downstream_plan``, and adds a passthrough column at
  the top level so the read-time filter can slice per-variable-value.

Helpers that don't need visitor state live at module scope so they can be tested
and composed independently. Instance methods on ``MaterializationTransformer`` are
reserved for operations that read ``self._current_cte_name``/``self.variable_infos``
or recurse via ``self.visit``.
"""

import copy
from dataclasses import dataclass
from typing import Any, Optional

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.visitor import CloningVisitor

from posthog.models.team import Team

from products.endpoints.backend.materialization.aggregates import extract_aggregate_name, get_reaggregation
from products.endpoints.backend.materialization.cte_propagation import (
    DownstreamCTEPlan,
    DownstreamCTEShape,
    _select_has_aggregate,
)
from products.endpoints.backend.materialization.range_buckets import _detect_range_variables
from products.endpoints.backend.materialization.types import MaterializableVariable


@dataclass
class MaterializedColumn:
    """A column in the materialized table with metadata for read-time re-aggregation."""

    expr: ast.Expr
    is_aggregate: bool
    reaggregate_fn: Optional[str] = None  # e.g. "sum" for count/sum, "min" for min, etc.


def transform_select_for_materialized_table(select_exprs: list[ast.Expr], team: Team) -> list[MaterializedColumn]:
    """Transform SELECT expressions to reference pre-computed columns in materialized table.

    Returns list of MaterializedColumn with re-aggregation metadata.

    Examples:
    - count() -> MaterializedColumn(Field(chain=["count()"]), is_aggregate=True, reaggregate_fn="sum")
    - count() as total -> MaterializedColumn(Field(chain=["total"]), is_aggregate=True, reaggregate_fn="sum")
    - toStartOfDay(timestamp) as date -> MaterializedColumn(Field(chain=["date"]), is_aggregate=False)
    """
    result: list[MaterializedColumn] = []
    for expr in select_exprs:
        agg_name = extract_aggregate_name(expr)
        is_agg = agg_name is not None
        reagg = get_reaggregation(agg_name) if agg_name else None
        reaggregate_fn = reagg.reaggregate_fn if reagg else None
        if isinstance(expr, ast.Alias):
            field = ast.Field(chain=[expr.alias])
        else:
            field = ast.Field(chain=[expr.to_hogql()])
        result.append(MaterializedColumn(expr=field, is_aggregate=is_agg, reaggregate_fn=reaggregate_fn))

    return result


def transform_query_for_materialization(
    hogql_query: dict[str, Any],
    variable_infos: MaterializableVariable | list[MaterializableVariable],
    team: Team,
    bucket_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Transform a HogQL query so it can be read from a materialized table.

    1. Removes WHERE clauses with variables
    2. Adds variable columns to SELECT (aliased by code_name) and GROUP BY (deduplicated)

    Example (single):
        Before: SELECT count(), date FROM events WHERE event = {variables.event_name} GROUP BY date
        After:  SELECT count(), date, event AS event_name FROM events GROUP BY date, event

    Example (multi, same column):
        Before: SELECT count() FROM events WHERE hour >= {variables.start} AND hour < {variables.end}
        After:  SELECT count(), hour AS start, hour AS end FROM events GROUP BY hour

    If bucket_overrides is provided, re-runs range pair detection with the overrides
    so that bucket_fn on the variable_infos is updated before the transform.
    """
    if isinstance(variable_infos, MaterializableVariable):
        variable_infos = [variable_infos]

    variable_infos = copy.deepcopy(variable_infos)

    # Re-apply range variable detection with overrides if provided
    if bucket_overrides:
        # Reset existing bucket_fn values so detection can re-apply with overrides
        for v in variable_infos:
            if v.bucket_fn is not None:
                v.bucket_fn = None
        _detect_range_variables(variable_infos, bucket_overrides=bucket_overrides)

    query_str = hogql_query.get("query")
    if not query_str:
        raise ValueError("No query string found")
    parsed_ast = parse_select(query_str)

    transformer = MaterializationTransformer(variable_infos)
    transformed_ast = transformer.visit(parsed_ast)

    transformed_query_str = to_printed_hogql(transformed_ast, team=team)

    return {
        **hogql_query,
        "query": transformed_query_str,
        "variables": {},
    }


# ---------------------------------------------------------------------------
# Module-level helpers (no self state — composable & independently testable)
# ---------------------------------------------------------------------------


def append_and(existing: Optional[ast.Expr], new_predicate: ast.Expr) -> ast.Expr:
    """AND-flatten ``new_predicate`` into ``existing``, collapsing nested ``ast.And``."""
    if existing is None:
        return new_predicate
    if isinstance(existing, ast.And):
        return ast.And(exprs=[*list(existing.exprs), new_predicate])
    return ast.And(exprs=[existing, new_predicate])


def build_variable_expression(var: MaterializableVariable) -> ast.Expr:
    """Expression used for the variable column without aliasing.

    Uses the original AST expression when available (e.g. for function calls
    like toDate(timestamp) that can't be reconstructed from column_chain).
    Always returns a fresh copy to avoid sharing AST nodes between SELECT and GROUP BY.
    When bucket_fn is set, wraps the column expression with the bucket function.
    """
    if var.column_ast is not None:
        base: ast.Expr = CloningVisitor().visit(var.column_ast)
    else:
        base = ast.Field(chain=list(var.column_chain))

    if var.bucket_fn:
        return ast.Call(name=var.bucket_fn, args=[base])

    return base


def build_variable_column(var: MaterializableVariable) -> ast.Expr:
    """Build the aliased SELECT column for ``var`` (``<expr> AS <code_name>``)."""
    return ast.Alias(
        alias=var.code_name,
        expr=build_variable_expression(var),
    )


def add_group_by_columns(
    node: ast.SelectQuery,
    vars_to_add: list[MaterializableVariable],
    *,
    use_field_ref: bool = False,
) -> None:
    """Add unique columns to GROUP BY, deduplicating by column_chain (or code_name when passthrough)."""
    existing_keys: set[str] = set()
    if node.group_by:
        for expr in node.group_by:
            if isinstance(expr, ast.Field):
                existing_keys.add(".".join(str(c) for c in expr.chain))

    seen_keys: set[str] = set()
    group_by_additions: list[ast.Expr] = []
    for var in vars_to_add:
        dedup_key = ".".join(var.column_chain) if var.column_chain else var.column_expression
        if use_field_ref:
            dedup_key = var.code_name
        if dedup_key not in seen_keys and dedup_key not in existing_keys:
            seen_keys.add(dedup_key)
            if use_field_ref:
                group_by_additions.append(ast.Field(chain=[var.code_name]))
            else:
                group_by_additions.append(build_variable_expression(var))

    if node.group_by:
        node.group_by = [*list(node.group_by), *group_by_additions]
    elif group_by_additions:
        node.group_by = group_by_additions


def _expr_contains_variable(node: ast.Expr) -> bool:
    """True if ``node`` references a ``{variables.*}`` placeholder directly or via a Call arg."""
    if isinstance(node, ast.Placeholder) and node.chain and node.chain[0] == "variables":
        return True
    if isinstance(node, ast.Call):
        return any(_expr_contains_variable(arg) for arg in node.args)
    return False


def _is_variable_comparison(node: ast.CompareOperation) -> bool:
    """True if either side of the comparison contains a variable placeholder."""
    return any(_expr_contains_variable(side) for side in (node.left, node.right))


def remove_variable_predicates(where_node: Optional[ast.Expr]) -> Optional[ast.Expr]:
    """Strip top-level comparisons that reference a variable placeholder, preserving the rest."""
    if where_node is None:
        return None

    if isinstance(where_node, ast.CompareOperation):
        return None if _is_variable_comparison(where_node) else where_node

    if isinstance(where_node, ast.And):
        filtered_exprs = [
            expr
            for expr in where_node.exprs
            if not (isinstance(expr, ast.CompareOperation) and _is_variable_comparison(expr))
        ]
        if not filtered_exprs:
            return None
        if len(filtered_exprs) == 1:
            return filtered_exprs[0]
        return ast.And(exprs=filtered_exprs)

    if isinstance(where_node, ast.Or):
        raise ValueError("Variables in OR conditions not supported")

    return where_node


def apply_downstream_plan(
    cte_expr: ast.Expr,
    var: MaterializableVariable,
    plan: DownstreamCTEPlan,
) -> ast.Expr:
    """Rewrite a cloned downstream CTE body so it emits ``var.code_name``.

    For UNION_ALL plans, recurses per-leg. For SelectQuery bodies, adds the alias
    to SELECT, extends GROUP BY (AGGREGATION) or WHERE equi-predicates (MULTI_JOIN).
    """
    if isinstance(cte_expr, ast.SelectSetQuery):
        if plan.shape != DownstreamCTEShape.UNION_ALL or not plan.leg_plans:
            return cte_expr
        new_initial = apply_downstream_plan(cte_expr.initial_select_query, var, plan.leg_plans[0])
        assert isinstance(new_initial, (ast.SelectQuery, ast.SelectSetQuery))
        new_subsequent: list[ast.SelectSetNode] = []
        for i, node in enumerate(cte_expr.subsequent_select_queries):
            leg_plan = plan.leg_plans[i + 1]
            rewritten = apply_downstream_plan(node.select_query, var, leg_plan)
            assert isinstance(rewritten, (ast.SelectQuery, ast.SelectSetQuery))
            new_subsequent.append(ast.SelectSetNode(select_query=rewritten, set_operator=node.set_operator))
        return ast.SelectSetQuery(
            initial_select_query=new_initial,
            subsequent_select_queries=new_subsequent,
            limit=cte_expr.limit,
            offset=cte_expr.offset,
            limit_percent=cte_expr.limit_percent,
            limit_with_ties=cte_expr.limit_with_ties,
        )

    if not isinstance(cte_expr, ast.SelectQuery):
        return cte_expr

    sources = plan.propagating_sources
    if not sources:
        return cte_expr
    first_alias = sources[0][0]

    select_addition = ast.Alias(
        alias=var.code_name,
        expr=ast.Field(chain=[first_alias, var.code_name]),
    )
    cte_expr.select = [*list(cte_expr.select or []), select_addition]

    if plan.shape == DownstreamCTEShape.AGGREGATION:
        group_by_field = ast.Field(chain=[var.code_name])
        if cte_expr.group_by:
            cte_expr.group_by = [*list(cte_expr.group_by), group_by_field]
        else:
            cte_expr.group_by = [group_by_field]

    if plan.shape == DownstreamCTEShape.MULTI_JOIN and len(sources) > 1:
        # Sources now hold rows for every variable value (WHERE was removed upstream).
        # Tie them together on the variable column so only matching-value rows survive.
        for alias, _ in sources[1:]:
            predicate = ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=[first_alias, var.code_name]),
                right=ast.Field(chain=[alias, var.code_name]),
            )
            cte_expr.where = append_and(cte_expr.where, predicate)

    return cte_expr


# ---------------------------------------------------------------------------
# Stateful visitor
# ---------------------------------------------------------------------------


class MaterializationTransformer(CloningVisitor):
    """CloningVisitor that removes variable WHERE clauses and adds columns to SELECT/GROUP BY.

    Tracks ``_current_cte_name`` so per-context logic (which variables apply here,
    whether we need a passthrough at the top level) can dispatch correctly. Heavy
    lifting is delegated to the module-level helpers above.
    """

    def __init__(self, variable_infos: list[MaterializableVariable]):
        super().__init__()
        self.variable_infos = variable_infos
        self._current_cte_name: Optional[str] = None

    def visit_select_query(self, node: ast.SelectQuery):
        new_ctes = self._process_ctes(node)

        # Visit the select query itself (without re-visiting CTEs)
        original_ctes = node.ctes
        node.ctes = None
        new_node = super().visit_select_query(node)
        node.ctes = original_ctes  # Restore original
        new_node.ctes = new_ctes

        # Add variable columns + remove variable WHERE clauses for current context
        vars_for_context = self._vars_for_current_context()
        if vars_for_context:
            self._add_variable_columns(new_node, vars_for_context)

        # Top-level query: add passthrough columns for CTE variables
        cte_vars = [v for v in self.variable_infos if v.cte_name is not None]
        if self._current_cte_name is None and cte_vars:
            self._add_cte_passthrough_columns(new_node, cte_vars)

        return new_node

    def _process_ctes(self, node: ast.SelectQuery) -> Optional[dict[str, ast.CTE]]:
        """Visit each CTE with context tracking; apply downstream plans after visiting."""
        if not node.ctes:
            return None
        new_ctes: dict[str, ast.CTE] = {}
        for cte_name, cte in node.ctes.items():
            prev_cte = self._current_cte_name
            self._current_cte_name = cte_name
            new_expr = self.visit(cte.expr)
            self._current_cte_name = prev_cte

            # SQL forces CTE definition order to be topological, so upstream
            # CTEs have already been rewritten to emit `code_name` by now.
            for var in self.variable_infos:
                if var.cte_name is None:
                    continue
                plan = var.downstream_plans.get(cte_name)
                if plan is None:
                    continue
                new_expr = apply_downstream_plan(new_expr, var, plan)

            new_ctes[cte_name] = ast.CTE(name=cte_name, expr=new_expr, cte_type=cte.cte_type)
        return new_ctes

    def _vars_for_current_context(self) -> list[MaterializableVariable]:
        """Return variables that apply to the current CTE/top-level context."""
        return [v for v in self.variable_infos if v.cte_name == self._current_cte_name]

    def _add_variable_columns(self, node: ast.SelectQuery, vars_for_context: list[MaterializableVariable]) -> None:
        """Add aliased variable columns to SELECT, update GROUP BY, and remove variable WHERE clauses."""
        select_additions = [build_variable_column(var) for var in vars_for_context]
        if node.select:
            node.select = [*list(node.select), *select_additions]
        else:
            node.select = select_additions

        if node.group_by is not None or self._current_cte_name is None:
            add_group_by_columns(node, vars_for_context)

        if node.where:
            node.where = remove_variable_predicates(node.where)

    def _add_cte_passthrough_columns(self, node: ast.SelectQuery, cte_vars: list[MaterializableVariable]) -> None:
        """Add passthrough columns + GROUP BY at top level for CTE-resident variables."""
        passthrough_additions: list[ast.Expr] = [ast.Field(chain=[var.code_name]) for var in cte_vars]
        if node.select:
            node.select = [*list(node.select), *passthrough_additions]
        else:
            node.select = passthrough_additions

        if node.group_by is not None or _select_has_aggregate(node):
            add_group_by_columns(node, cte_vars, use_field_ref=True)
