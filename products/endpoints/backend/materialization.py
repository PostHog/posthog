import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from posthog.schema import HogQLQuery, HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.functions.aggregations import COMBINATORS
from posthog.hogql.functions.mapping import find_hogql_aggregation
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.timings import HogQLTimings
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor

from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models.team import Team


class VariableInHavingClauseError(ValueError):
    """Raised when a variable is used in a HAVING clause, which is not supported for materialization."""


def inject_series_index(query_ast: ast.SelectQuery | ast.SelectSetQuery) -> None:
    """Add a __series_index literal column to each sub-query in a UNION ALL.

    For single SelectQuery: adds ``0 AS __series_index``.
    For SelectSetQuery (multi-series UNION ALL): adds ``N AS __series_index``
    to each sub-query so the materialized table can distinguish series.
    """
    if isinstance(query_ast, ast.SelectQuery):
        _add_series_index_to_select(query_ast, 0)
    elif isinstance(query_ast, ast.SelectSetQuery):
        all_queries = query_ast.select_queries()
        for i, sub_query in enumerate(all_queries):
            if isinstance(sub_query, ast.SelectQuery):
                _add_series_index_to_select(sub_query, i)


def _add_series_index_to_select(query: ast.SelectQuery, index: int) -> None:
    """Add ``{index} AS __series_index`` to a single SELECT query."""
    series_col = ast.Alias(alias="__series_index", expr=ast.Constant(value=index))
    query.select = [*list(query.select or []), series_col]

    if query.group_by is not None:
        query.group_by = [*list(query.group_by), ast.Field(chain=["__series_index"])]


def convert_insight_query_to_hogql(query: dict[str, Any], team: Team) -> dict[str, Any]:
    query_kind = query.get("kind")

    if query_kind == "HogQLQuery":
        return query

    query_runner = get_query_runner(
        query=query,
        team=team,
        timings=HogQLTimings(),
        modifiers=HogQLQueryModifiers(),
    )

    combined_query_ast = query_runner.to_query()

    # Only inject __series_index for types that have a corresponding transformer
    SERIES_INDEX_QUERY_TYPES = {"TrendsQuery", "LifecycleQuery", "RetentionQuery"}
    if query_kind in SERIES_INDEX_QUERY_TYPES:
        inject_series_index(combined_query_ast)

    hogql_string = to_printed_hogql(combined_query_ast, team=team, modifiers=query_runner.modifiers)

    result = HogQLQuery(query=hogql_string, modifiers=query_runner.modifiers).model_dump()
    if "variables" in query:
        result["variables"] = query["variables"]
    return result


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

    # Plans for propagating this variable's column through each downstream CTE.
    # Keyed by downstream CTE name. Populated by the analyzer; consumed by the transformer.
    downstream_plans: dict[str, "DownstreamCTEPlan"] = field(default_factory=dict)


@dataclass
class VariableUsageInWhere:
    """Details of how a variable is used in a WHERE clause"""

    column_chain: list[str]
    column_expression: str
    operator: ast.CompareOperationOp
    column_ast: Optional[ast.Expr] = None
    value_wrapper_fns: Optional[list[str]] = None


RANGE_OPS = frozenset(
    {
        ast.CompareOperationOp.GtEq,
        ast.CompareOperationOp.Gt,
        ast.CompareOperationOp.Lt,
        ast.CompareOperationOp.LtEq,
    }
)


@dataclass(frozen=True)
class AggregateReaggregation:
    """Defines how a base aggregate function is re-aggregated after bucketed materialization."""

    reaggregate_fn: str  # function to apply at read time (e.g., "sum" for count)


# Base functions that CAN be re-aggregated, and how.
# A combined function (e.g., sumIf) inherits from its base (sum).
REAGGREGATABLE_BASE_FUNCTIONS: dict[str, AggregateReaggregation] = {
    "count": AggregateReaggregation(reaggregate_fn="sum"),
    "sum": AggregateReaggregation(reaggregate_fn="sum"),
    "min": AggregateReaggregation(reaggregate_fn="min"),
    "max": AggregateReaggregation(reaggregate_fn="max"),
}


def _strip_combinators(func_name: str) -> str | None:
    """Strip ClickHouse combinator suffixes to find the base aggregate function.

    Uses the COMBINATORS registry from posthog.hogql.functions.aggregations.
    Returns the base function name (lowercased), or None if no match found.

    Examples:
        "sumIf" -> "sum"
        "countArrayIf" -> "count"
        "uniqMerge" -> "uniq" (but uniq is not in REAGGREGATABLE_BASE_FUNCTIONS)
        "count" -> "count"
    """
    name_lower = func_name.lower()
    if name_lower in REAGGREGATABLE_BASE_FUNCTIONS:
        return name_lower

    sorted_suffixes = sorted(COMBINATORS.keys(), key=len, reverse=True)

    def strip_recursive(name: str) -> str:
        for suffix in sorted_suffixes:
            if name.endswith(suffix.lower()) and len(name) > len(suffix):
                return strip_recursive(name[: -len(suffix)])
        return name

    base = strip_recursive(name_lower)
    return base if base != name_lower or base in REAGGREGATABLE_BASE_FUNCTIONS else None


def get_reaggregation(func_name: str) -> AggregateReaggregation | None:
    """Look up how to re-aggregate a (possibly combined) aggregate function.

    Returns AggregateReaggregation if the function can be re-aggregated, None otherwise.
    Handles ClickHouse combinators by stripping suffixes to find the base function.

    Examples:
        "count" -> AggregateReaggregation(reaggregate_fn="sum")
        "sumIf" -> AggregateReaggregation(reaggregate_fn="sum")
        "avg" -> None (not re-aggregatable)
        "uniqArrayIf" -> None (base "uniq" not in registry)
    """
    base = _strip_combinators(func_name)
    if base is None:
        return None
    return REAGGREGATABLE_BASE_FUNCTIONS.get(base)


def _is_aggregate(func_name: str) -> bool:
    """Whether ``func_name`` resolves to a known aggregate, registered or combinator-derived.

    ``find_hogql_aggregation`` only covers names in the registry; combinator-derived names
    (``sumIf``, ``maxIf``, ``countArrayIf``, …) live outside it and need ``_strip_combinators``.
    """
    return find_hogql_aggregation(func_name) is not None or _strip_combinators(func_name) is not None


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


def analyze_variables_for_materialization(
    hogql_query: dict[str, Any],
    bucket_overrides: dict[str, str] | None = None,
) -> tuple[bool, str, list[MaterializableVariable]]:
    """
    Check if query variables can be materialized.

    Each variable must be used in a WHERE clause with a supported operator
    (=, >=, >, <, <=). Multiple variables are supported.

    Returns:
        (can_materialize, reason, variable_infos)
    """
    query_str = hogql_query.get("query")
    if not query_str:
        return False, "No query string found", []

    try:
        ast_node = parse_select(query_str)
    except Exception as e:
        capture_exception(e)
        return False, "Failed to parse query.", []

    finder = VariablePlaceholderFinder()
    finder.visit(ast_node)

    if not finder.variable_placeholders:
        return False, "No variables found", []

    variables_dict = hogql_query.get("variables", {})
    result_vars: list[MaterializableVariable] = []
    seen_code_names: set[str] = set()

    for placeholder in finder.variable_placeholders:
        if not placeholder.chain or len(placeholder.chain) < 2:
            return False, "Invalid variable placeholder format", []

        code_name = str(placeholder.chain[1])
        if code_name in seen_code_names:
            continue
        seen_code_names.add(code_name)

        try:
            all_usages = find_all_variable_usages(ast_node, placeholder)
        except VariableInHavingClauseError:
            return False, "Variable used in HAVING clause are not supported for materialization.", []
        except ValueError as e:
            capture_exception(e)
            return False, "Invalid variable usage in WHERE clause.", []

        if not all_usages:
            return False, "Variable not used in WHERE clause", []

        # Determine CTE context for this variable
        cte_names = {cte_name for cte_name, _ in all_usages}
        if len(cte_names) > 1:
            # Variable used in multiple different locations (e.g. two CTEs, or CTE + top-level)
            has_top_level = None in cte_names
            has_cte = any(n is not None for n in cte_names)
            if has_top_level and has_cte:
                return False, "Variable used in both CTE and top-level query is not yet supported", []
            return False, "Variable used in multiple CTEs is not yet supported", []

        cte_name = next(iter(cte_names))
        # Use the first usage for column info (all usages of the same variable should be consistent)
        variable_usage = all_usages[0][1]

        if variable_usage.operator not in SUPPORTED_MATERIALIZATION_OPS:
            return (
                False,
                f"Unsupported operator {variable_usage.operator}, supported: =, >=, >, <, <=",
                [],
            )

        variable_id = next(
            (var_id for var_id, var_data in variables_dict.items() if var_data.get("code_name") == code_name),
            None,
        )

        if not variable_id:
            return False, "Variable metadata not found", []

        result_vars.append(
            MaterializableVariable(
                variable_id=variable_id,
                code_name=code_name,
                column_chain=variable_usage.column_chain,
                column_expression=variable_usage.column_expression,
                operator=variable_usage.operator,
                column_ast=variable_usage.column_ast,
                value_wrapper_fns=variable_usage.value_wrapper_fns,
                cte_name=cte_name,
            )
        )

    # Detect range variables and set bucket_fn for bucketed materialization.
    # Single-bound ranges (e.g., just >= start) are supported — we materialize all data
    # bucketed and filter at read time with the user's value.
    _detect_range_variables(result_vars, bucket_overrides=bucket_overrides)

    # If range variables exist, ALL aggregate functions must be re-aggregatable
    has_range_vars = any(v.bucket_fn is not None for v in result_vars)
    if has_range_vars and isinstance(ast_node, ast.SelectQuery) and ast_node.select:
        for expr in ast_node.select:
            agg_name = _extract_aggregate_name(expr)
            if agg_name and get_reaggregation(agg_name) is None:
                return (
                    False,
                    f"Aggregate function '{agg_name}' cannot be re-aggregated for range variable materialization",
                    [],
                )

    # Safety check: CTE variables + top-level JOINs produce wrong results.
    # Removing a CTE's WHERE changes its row cardinality, which changes JOIN
    # output. Filtering after materialization can't recover the original semantics
    # (e.g. LEFT JOIN non-matches get NULL for the variable column and are lost).
    has_cte_vars = any(v.cte_name is not None for v in result_vars)
    if has_cte_vars and isinstance(ast_node, ast.SelectQuery) and _has_joins(ast_node):
        return False, "CTE variables with JOINs in the top-level query are not supported for materialization", []

    # Propagation planning: for each CTE-bound variable, classify every downstream
    # CTE so the transformer can rewrite SELECT / GROUP BY / WHERE to carry the
    # variable column from the variable-carrying CTE to the terminal CTE.
    if has_cte_vars and isinstance(ast_node, ast.SelectQuery) and ast_node.ctes:
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
                    return False, plan.reject_reason, []
                plans[d_cte_name] = plan
            var.downstream_plans = plans

    return True, "OK", result_vars


def _has_joins(node: ast.SelectQuery) -> bool:
    """Check if a SelectQuery has any JOINs (next_join on select_from)."""
    return node.select_from is not None and node.select_from.next_join is not None


# ---------------------------------------------------------------------------
# CTE variable propagation: graph helpers + downstream shape classifier
# ---------------------------------------------------------------------------
#
# When a variable lives inside a CTE and downstream CTEs read from it,
# the materialized terminal table must still carry the variable column so the
# read-time filter can slice rows per-variable-value. These helpers walk the
# CTE reference graph, classify each downstream CTE's shape, and return a
# plan object the transformer uses to rewrite SELECT / GROUP BY / WHERE.


# Join types between propagating CTEs that preserve per-value row identity
# under a CROSS-JOIN + equi-predicate rewrite. Outer joins break this (see
# product_data reasoning in the plan doc), so they're explicitly rejected.
_SAFE_PROPAGATION_JOIN_TYPES = frozenset({None, "JOIN", "INNER JOIN", "CROSS JOIN"})


class DownstreamCTEShape(Enum):
    PROJECTION = "projection"
    AGGREGATION = "aggregation"
    DISTINCT = "distinct"
    MULTI_JOIN = "multi_join"
    UNION_ALL = "union_all"


@dataclass
class DownstreamCTEPlan:
    """How the transformer should propagate a variable through a downstream CTE."""

    cte_name: str
    shape: DownstreamCTEShape
    # (alias_or_cte_name, cte_name) pairs for every propagating CTE read in this CTE.
    # For UNION_ALL, this is left empty; each leg carries its own nested plan.
    propagating_sources: list[tuple[str, str]] = field(default_factory=list)
    leg_plans: list["DownstreamCTEPlan"] = field(default_factory=list)
    reject_reason: Optional[str] = None


class _CTEReferenceCollector(TraversingVisitor):
    """Collect names of sibling CTEs referenced anywhere in an expression subtree.

    A nested ``WITH`` defining the same name shadows the outer sibling, so references
    inside the nested scope are excluded.
    """

    def __init__(self, known_ctes: set[str]):
        super().__init__()
        self._known_stack: list[set[str]] = [known_ctes]
        self.referenced: set[str] = set()

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        shadowed = (set(node.ctes.keys()) & self._known_stack[-1]) if node.ctes else set()
        if shadowed:
            self._known_stack.append(self._known_stack[-1] - shadowed)
            try:
                super().visit_select_query(node)
            finally:
                self._known_stack.pop()
        else:
            super().visit_select_query(node)

    def visit_join_expr(self, node: ast.JoinExpr):
        if isinstance(node.table, ast.Field) and len(node.table.chain) == 1:
            name = str(node.table.chain[0])
            if name in self._known_stack[-1]:
                self.referenced.add(name)
        super().visit_join_expr(node)


def _build_cte_read_graph(node: ast.SelectQuery) -> dict[str, set[str]]:
    """Map each CTE name to the sibling CTE names its body references (transitively via subtree walk)."""
    if not node.ctes:
        return {}
    cte_names = set(node.ctes.keys())
    graph: dict[str, set[str]] = {}
    for name, cte in node.ctes.items():
        collector = _CTEReferenceCollector(cte_names - {name})
        collector.visit(cte.expr)
        graph[name] = collector.referenced
    return graph


def _reads_from(graph: dict[str, set[str]], source: str, target: str, visited: set[str]) -> bool:
    if source in visited:
        return False
    visited.add(source)
    direct = graph.get(source, set())
    if target in direct:
        return True
    return any(_reads_from(graph, ref, target, visited) for ref in direct)


def _downstream_ctes(graph: dict[str, set[str]], start: str) -> set[str]:
    """Return every CTE that transitively reads from ``start`` (excludes ``start`` itself)."""
    result: set[str] = set()
    for name in graph:
        if name == start:
            continue
        if _reads_from(graph, name, start, set()):
            result.add(name)
    return result


def _topological_order(graph: dict[str, set[str]], subset: set[str]) -> list[str]:
    """Order CTEs so each appears after any CTE it reads from (within ``subset``)."""
    result: list[str] = []
    visited: set[str] = set()

    def visit(n: str) -> None:
        if n in visited or n not in subset:
            return
        visited.add(n)
        for dep in graph.get(n, set()):
            visit(dep)
        result.append(n)

    for n in subset:
        visit(n)
    return result


def _normalize_join_type(join_type: Optional[str]) -> Optional[str]:
    """Strip a leading ``GLOBAL `` prefix so classification keys match the base join type."""
    if join_type is None:
        return None
    if join_type.startswith("GLOBAL "):
        return join_type.removeprefix("GLOBAL ")
    return join_type


def _select_column_name(expr: ast.Expr) -> Optional[str]:
    """The name a SELECT expression emits — alias, or a single-segment field chain."""
    if isinstance(expr, ast.Alias):
        return expr.alias
    if isinstance(expr, ast.Field) and len(expr.chain) == 1:
        return str(expr.chain[0])
    return None


def _collect_propagating_sources_top_level(
    select_from: Optional[ast.JoinExpr],
    propagating: set[str],
) -> tuple[list[tuple[str, str]], Optional[str]]:
    """Walk the top-level ``select_from`` chain, collecting propagating CTE refs.

    Returns ``(sources, reject_reason)``. ``reject_reason`` is non-None if any
    JoinExpr in the chain references a propagating CTE via an unsupported join type.
    """
    sources: list[tuple[str, str]] = []
    cur = select_from
    while cur is not None:
        is_prop = False
        cte_name: Optional[str] = None
        if isinstance(cur.table, ast.Field) and len(cur.table.chain) == 1:
            name = str(cur.table.chain[0])
            if name in propagating:
                is_prop = True
                cte_name = name
        if is_prop and cte_name is not None:
            join_type = _normalize_join_type(cur.join_type)
            if join_type not in _SAFE_PROPAGATION_JOIN_TYPES:
                return (
                    [],
                    f"CTE variable propagation requires CROSS/INNER joins between propagating CTEs; "
                    f"{cur.join_type} not supported",
                )
            alias = cur.alias or cte_name
            sources.append((alias, cte_name))
        cur = cur.next_join
    return sources, None


def _has_nested_propagating_reference(node: Optional[ast.Expr], propagating: set[str]) -> bool:
    """Detect a propagating-CTE reference inside a subquery (e.g. ``FROM (SELECT * FROM prop)``)."""
    if node is None:
        return False

    class _Finder(TraversingVisitor):
        def __init__(self) -> None:
            super().__init__()
            self.found = False

        def visit_select_query(self, n: ast.SelectQuery) -> None:
            if n.select_from is not None:
                self.visit(n.select_from)

        def visit_select_set_query(self, n: ast.SelectSetQuery) -> None:
            for leg in n.select_queries():
                self.visit(leg)

        def visit_join_expr(self, n: ast.JoinExpr) -> None:
            if isinstance(n.table, ast.Field) and len(n.table.chain) == 1:
                if str(n.table.chain[0]) in propagating:
                    self.found = True
                    return
            if isinstance(n.table, ast.SelectQuery | ast.SelectSetQuery):
                self.visit(n.table)
            if n.next_join is not None:
                self.visit(n.next_join)

    finder = _Finder()
    finder.visit(node)
    return finder.found


def _select_from_has_nested_reference(
    select_from: Optional[ast.JoinExpr],
    propagating: set[str],
) -> bool:
    """Return True if any join in the top chain uses a subquery that references a propagating CTE."""
    cur = select_from
    while cur is not None:
        if isinstance(cur.table, ast.SelectQuery | ast.SelectSetQuery):
            if _has_nested_propagating_reference(cur.table, propagating):
                return True
        cur = cur.next_join
    return False


class _NonTopPropagatingReferenceFinder(TraversingVisitor):
    """Flag a propagating-CTE reference outside the top-level FROM chain.

    Top-level FROM references are valid propagation sources (handled separately).
    Anywhere else — scalar subquery in WHERE/SELECT, JOIN ON, LIMIT BY — would need
    a correlated subquery to carry the variable column, which the transformer can't
    produce, so the caller must reject. Nested ``WITH`` shadowing an outer name is
    honored.
    """

    def __init__(self, propagating: set[str], top_chain_join_ids: set[int]) -> None:
        super().__init__()
        self._propagating_stack: list[set[str]] = [propagating]
        self.top_chain_join_ids = top_chain_join_ids
        self.found = False

    def visit(self, node: ast.AST | None) -> None:
        if self.found or node is None:
            return
        super().visit(node)

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        shadowed = (set(node.ctes.keys()) & self._propagating_stack[-1]) if node.ctes else set()
        if shadowed:
            self._propagating_stack.append(self._propagating_stack[-1] - shadowed)
            try:
                super().visit_select_query(node)
            finally:
                self._propagating_stack.pop()
        else:
            super().visit_select_query(node)

    def visit_join_expr(self, n: ast.JoinExpr) -> None:
        if self.found:
            return
        if id(n) not in self.top_chain_join_ids:
            if (
                isinstance(n.table, ast.Field)
                and len(n.table.chain) == 1
                and str(n.table.chain[0]) in self._propagating_stack[-1]
            ):
                self.found = True
                return
        super().visit_join_expr(n)


def _body_has_non_top_from_propagating_reference(
    cte: ast.SelectQuery,
    propagating: set[str],
) -> bool:
    """Return True if any part of ``cte`` other than its top-level ``select_from`` chain
    references a propagating CTE."""
    top_chain_join_ids: set[int] = set()
    cur: Optional[ast.JoinExpr] = cte.select_from
    while cur is not None:
        top_chain_join_ids.add(id(cur))
        cur = cur.next_join

    finder = _NonTopPropagatingReferenceFinder(propagating, top_chain_join_ids)
    finder.visit(cte)
    return finder.found


def _emits_column(select_query: ast.SelectQuery, column_name: str) -> bool:
    for expr in select_query.select or []:
        name = _select_column_name(expr)
        if name == column_name:
            return True
    return False


def _classify_downstream_cte(
    cte_name: str,
    cte_expr: ast.Expr,
    propagating: set[str],
    code_names: list[str],
) -> DownstreamCTEPlan:
    """Classify a downstream CTE's shape; produce a plan or a rejection reason."""

    if isinstance(cte_expr, ast.SelectSetQuery):
        non_union_legs = [node.set_operator for node in cte_expr.subsequent_select_queries]
        if any(op != "UNION ALL" for op in non_union_legs):
            return DownstreamCTEPlan(
                cte_name=cte_name,
                shape=DownstreamCTEShape.UNION_ALL,
                reject_reason="Only UNION ALL is supported for propagation across set operations",
            )

        leg_plans: list[DownstreamCTEPlan] = []
        for i, leg in enumerate(cte_expr.select_queries()):
            if not isinstance(leg, ast.SelectQuery):
                return DownstreamCTEPlan(
                    cte_name=cte_name,
                    shape=DownstreamCTEShape.UNION_ALL,
                    reject_reason=(f"Variable propagation failed on UNION leg: nested set queries are not supported"),
                )
            leg_plan = _classify_downstream_cte(f"{cte_name}#leg{i}", leg, propagating, code_names)
            if leg_plan.reject_reason:
                return DownstreamCTEPlan(
                    cte_name=cte_name,
                    shape=DownstreamCTEShape.UNION_ALL,
                    reject_reason=f"Variable propagation failed on UNION leg: {leg_plan.reject_reason}",
                )
            if not leg_plan.propagating_sources and leg_plan.shape != DownstreamCTEShape.UNION_ALL:
                return DownstreamCTEPlan(
                    cte_name=cte_name,
                    shape=DownstreamCTEShape.UNION_ALL,
                    reject_reason=("Variable propagation failed on UNION leg: leg has no propagating CTE source"),
                )
            leg_plans.append(leg_plan)

        return DownstreamCTEPlan(
            cte_name=cte_name,
            shape=DownstreamCTEShape.UNION_ALL,
            leg_plans=leg_plans,
        )

    if not isinstance(cte_expr, ast.SelectQuery):
        return DownstreamCTEPlan(
            cte_name=cte_name,
            shape=DownstreamCTEShape.PROJECTION,
            reject_reason=f"Unsupported CTE body type: {type(cte_expr).__name__}",
        )

    if cte_expr.window_exprs:
        return DownstreamCTEPlan(
            cte_name=cte_name,
            shape=DownstreamCTEShape.PROJECTION,
            reject_reason="Window functions in downstream CTEs of a variable CTE are not yet supported for materialization",
        )

    sources, reject = _collect_propagating_sources_top_level(cte_expr.select_from, propagating)
    if reject:
        return DownstreamCTEPlan(
            cte_name=cte_name,
            shape=DownstreamCTEShape.PROJECTION,
            reject_reason=reject,
        )

    if _select_from_has_nested_reference(cte_expr.select_from, propagating):
        return DownstreamCTEPlan(
            cte_name=cte_name,
            shape=DownstreamCTEShape.PROJECTION,
            reject_reason="CTE variable propagation requires top-level FROM references; nested subquery reference not supported",
        )

    if _body_has_non_top_from_propagating_reference(cte_expr, propagating):
        return DownstreamCTEPlan(
            cte_name=cte_name,
            shape=DownstreamCTEShape.PROJECTION,
            reject_reason=(
                "CTE variable propagation requires top-level FROM references; "
                "scalar subquery reading from a propagating CTE not supported"
            ),
        )

    if not sources:
        return DownstreamCTEPlan(
            cte_name=cte_name,
            shape=DownstreamCTEShape.PROJECTION,
            reject_reason="Downstream CTE does not read from any propagating CTE",
        )

    for code_name in code_names:
        if _emits_column(cte_expr, code_name):
            return DownstreamCTEPlan(
                cte_name=cte_name,
                shape=DownstreamCTEShape.PROJECTION,
                reject_reason=f"Variable code_name '{code_name}' collides with existing column in downstream CTE {cte_name}",
            )

    if len(sources) >= 2:
        shape = DownstreamCTEShape.MULTI_JOIN
    elif cte_expr.distinct:
        shape = DownstreamCTEShape.DISTINCT
    elif cte_expr.group_by or _select_has_aggregate(cte_expr):
        shape = DownstreamCTEShape.AGGREGATION
    else:
        shape = DownstreamCTEShape.PROJECTION

    return DownstreamCTEPlan(
        cte_name=cte_name,
        shape=shape,
        propagating_sources=sources,
    )


def _select_has_aggregate(node: ast.SelectQuery) -> bool:
    class _AggFinder(TraversingVisitor):
        def __init__(self) -> None:
            super().__init__()
            self.found = False

        def visit_call(self, n: ast.Call) -> None:
            if _is_aggregate(n.name):
                self.found = True
                return
            super().visit_call(n)

    finder = _AggFinder()
    for expr in node.select or []:
        finder.visit(expr)
        if finder.found:
            return True
    return False


class VariablePlaceholderFinder(TraversingVisitor):
    """Find all variable placeholders in the AST"""

    def __init__(self):
        super().__init__()
        self.variable_placeholders: list[ast.Placeholder] = []

    def visit_placeholder(self, node: ast.Placeholder):
        if node.chain and node.chain[0] == "variables":
            self.variable_placeholders.append(node)


def find_variable_in_where(
    ast_node: ast.SelectQuery | ast.SelectSetQuery, placeholder: ast.Placeholder
) -> Optional[VariableUsageInWhere]:
    """
    Walk AST to find where the placeholder is used in WHERE clause.
    Returns column being compared and operator.
    """
    if not isinstance(ast_node, ast.SelectQuery):
        return None
    finder = VariableInWhereFinder(placeholder)
    finder.visit(ast_node)
    return finder.result


def find_all_variable_usages(
    ast_node: ast.SelectQuery | ast.SelectSetQuery, placeholder: ast.Placeholder
) -> list[tuple[Optional[str], VariableUsageInWhere]]:
    """Find all usages of a variable in WHERE clauses, including inside CTEs.

    Returns list of (cte_name, usage) tuples. cte_name is None for top-level query.
    """
    if not isinstance(ast_node, ast.SelectQuery):
        return []
    finder = VariableInWhereFinder(placeholder)
    finder.visit(ast_node)
    return finder.all_results


class VariableInWhereFinder(TraversingVisitor):
    """Find how a variable is used in WHERE clause, including inside CTEs."""

    def __init__(self, target_placeholder: ast.Placeholder):
        super().__init__()
        self.target = target_placeholder
        self.all_results: list[tuple[Optional[str], VariableUsageInWhere]] = []
        self.in_where = False
        self._current_cte_name: Optional[str] = None

    @property
    def result(self) -> Optional[VariableUsageInWhere]:
        """Backward-compat: return first match's usage."""
        return self.all_results[0][1] if self.all_results else None

    def visit_select_query(self, node: ast.SelectQuery):
        if node.having:
            finder = VariablePlaceholderFinder()
            finder.visit(node.having)
            if any(p.chain == self.target.chain for p in finder.variable_placeholders):
                raise VariableInHavingClauseError()

        # Visit CTEs first (they're part of this SelectQuery)
        if node.ctes:
            for cte_name, cte in node.ctes.items():
                prev_cte = self._current_cte_name
                self._current_cte_name = cte_name
                self.visit(cte.expr)
                self._current_cte_name = prev_cte

        if node.where:
            self.in_where = True
            self.visit(node.where)
            self.in_where = False

    def visit_compare_operation(self, node: ast.CompareOperation):
        if not self.in_where:
            return

        field_side = None
        variable_side = None
        if self._contains_target_placeholder(node.right):
            field_side = node.left
            variable_side = node.right
        elif self._contains_target_placeholder(node.left):
            field_side = node.right
            variable_side = node.left

        if not field_side:
            return

        wrapper_fns = self._extract_wrapper_fns(variable_side)

        if isinstance(field_side, ast.Field):
            column_chain = [str(item) for item in field_side.chain]
            self.all_results.append(
                (
                    self._current_cte_name,
                    VariableUsageInWhere(
                        column_chain=column_chain,
                        column_expression=".".join(column_chain),
                        operator=node.op,
                        value_wrapper_fns=wrapper_fns,
                    ),
                )
            )
        elif isinstance(field_side, ast.Call):
            column_chain = self._extract_column_chain_from_call(field_side)
            self.all_results.append(
                (
                    self._current_cte_name,
                    VariableUsageInWhere(
                        column_chain=column_chain,
                        column_expression=".".join(column_chain) if column_chain else str(field_side),
                        operator=node.op,
                        column_ast=field_side if not column_chain else None,
                        value_wrapper_fns=wrapper_fns,
                    ),
                )
            )

    def _contains_target_placeholder(self, node: ast.Expr) -> bool:
        """Check if an expression is or contains the target placeholder (e.g. inside toDate(...))."""
        if isinstance(node, ast.Placeholder) and node.chain == self.target.chain:
            return True
        if isinstance(node, ast.Call):
            return any(self._contains_target_placeholder(arg) for arg in node.args)
        return False

    @staticmethod
    def _extract_wrapper_fns(node: Optional[ast.Expr]) -> Optional[list[str]]:
        """Extract the chain of wrapping function names from outermost to innermost.

        For toDate(toStartOfMonth({variables.x})), returns ["toDate", "toStartOfMonth"].
        """
        fns: list[str] = []
        current = node
        while isinstance(current, ast.Call) and len(current.args) == 1:
            fns.append(current.name)
            current = current.args[0]
        return fns or None

    def _extract_column_chain_from_call(self, call: ast.Call) -> list[str]:
        if call.name == "JSONExtractString" and len(call.args) >= 2:
            if isinstance(call.args[0], ast.Field) and isinstance(call.args[1], ast.Constant):
                field_chain = [str(item) for item in call.args[0].chain]
                return [*field_chain, str(call.args[1].value)]
        return []


SUPPORTED_BUCKET_FUNCTIONS: dict[str, str] = {
    "minute": "toStartOfMinute",
    "fifteen_minutes": "toStartOfFifteenMinutes",
    "hour": "toStartOfHour",
    "day": "toStartOfDay",
    "week": "toStartOfWeek",
    "month": "toStartOfMonth",
}


def _is_property_column(column_chain: list[str]) -> bool:
    """Check if a column chain references a properties field (e.g. properties.price)."""
    return "properties" in column_chain


def _detect_range_variables(
    variables: list[MaterializableVariable],
    bucket_overrides: dict[str, str] | None = None,
) -> None:
    """Detect range variables and set bucket_fn for bucketed materialization.

    Any variable with a range operator on a plain column (no column_ast)
    gets bucket_fn set. For single-bound ranges, we materialize all data
    bucketed and filter at read time with the user's value.

    Properties columns (e.g. properties.price) are skipped unless the user
    explicitly provides a bucket_override — bucket functions like toStartOfDay
    only make sense on DateTime columns, not on string/numeric properties.
    """
    for var in variables:
        if var.column_ast is not None:
            continue
        if var.operator not in RANGE_OPS:
            continue

        col_key = ".".join(var.column_chain) if var.column_chain else var.column_expression

        if bucket_overrides and col_key in bucket_overrides:
            override = bucket_overrides[col_key]
            if override not in SUPPORTED_BUCKET_FUNCTIONS:
                raise ValueError(
                    f"Unsupported bucket override '{override}'. Supported: {list(SUPPORTED_BUCKET_FUNCTIONS.keys())}"
                )
            var.bucket_fn = SUPPORTED_BUCKET_FUNCTIONS[override]
        elif not _is_property_column(var.column_chain):
            var.bucket_fn = "toStartOfDay"


def _extract_aggregate_name(expr: ast.Expr) -> Optional[str]:
    """Extract the aggregate function name from a SELECT expression, if any.

    Returns lowercased names so downstream lookups (REAGGREGATABLE_BASE_FUNCTIONS,
    get_reaggregation) match regardless of source casing. Both count(DISTINCT x) and
    countDistinct(x) (in any case) collapse to the camelCase sentinel "countDistinct"
    so they stay out of REAGGREGATABLE_BASE_FUNCTIONS — merging distinct counts via
    sum would double-count across partitions.
    """
    if isinstance(expr, ast.Alias):
        return _extract_aggregate_name(expr.expr)
    if isinstance(expr, ast.Call):
        name_lower = expr.name.lower()
        if name_lower == "count" and getattr(expr, "distinct", False):
            return "countDistinct"
        if name_lower == "countdistinct":
            return "countDistinct"
        if _is_aggregate(expr.name):
            return name_lower
    return None


@dataclass
class MaterializedColumn:
    """A column in the materialized table with metadata for read-time re-aggregation."""

    expr: ast.Expr
    is_aggregate: bool
    reaggregate_fn: Optional[str] = None  # e.g. "sum" for count/sum, "min" for min, etc.


def transform_select_for_materialized_table(select_exprs: list[ast.Expr], team: Team) -> list[MaterializedColumn]:
    """
    Transform SELECT expressions to reference pre-computed columns in materialized table.

    Returns list of MaterializedColumn with re-aggregation metadata.

    Examples:
    - count() -> MaterializedColumn(Field(chain=["count()"]), is_aggregate=True, reaggregate_fn="sum")
    - count() as total -> MaterializedColumn(Field(chain=["total"]), is_aggregate=True, reaggregate_fn="sum")
    - toStartOfDay(timestamp) as date -> MaterializedColumn(Field(chain=["date"]), is_aggregate=False)
    """
    result: list[MaterializedColumn] = []
    for expr in select_exprs:
        agg_name = _extract_aggregate_name(expr)
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
    """
    Transform query by:
    1. Removing WHERE clauses with variables
    2. Adding variable columns to SELECT (aliased by code_name) and GROUP BY (deduplicated)

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


class MaterializationTransformer(CloningVisitor):
    """AST transformer that removes variable WHERE clauses and adds columns to SELECT and GROUP BY.

    Each variable gets an aliased column in SELECT (aliased by code_name).
    GROUP BY is deduplicated by column_chain to handle same-column range variables
    (e.g., hour >= start AND hour < end → GROUP BY hour, not GROUP BY hour, hour).

    CTE-aware: when variables live in a CTE, the CTE gets the column addition + WHERE removal,
    and the top-level query gets a passthrough column from the CTE.
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
        """Process CTEs with proper context tracking, returning transformed CTE dict."""
        if not node.ctes:
            return None
        new_ctes: dict[str, ast.CTE] = {}
        for cte_name, cte in node.ctes.items():
            prev_cte = self._current_cte_name
            self._current_cte_name = cte_name
            new_expr = self.visit(cte.expr)
            self._current_cte_name = prev_cte

            # After the CTE body has been cloned/visited, propagate any variable
            # whose plan targets this CTE. Definition order is also topological,
            # so upstream CTEs have already been rewritten to emit code_name.
            for var in self.variable_infos:
                if var.cte_name is None:
                    continue
                plan = var.downstream_plans.get(cte_name)
                if plan is None:
                    continue
                new_expr = self._apply_downstream_plan(new_expr, var, plan)

            new_ctes[cte_name] = ast.CTE(name=cte_name, expr=new_expr, cte_type=cte.cte_type)
        return new_ctes

    def _apply_downstream_plan(
        self,
        cte_expr: ast.Expr,
        var: MaterializableVariable,
        plan: DownstreamCTEPlan,
    ) -> ast.Expr:
        """Rewrite a cloned downstream CTE body so it emits ``var.code_name``."""
        if isinstance(cte_expr, ast.SelectSetQuery):
            if plan.shape != DownstreamCTEShape.UNION_ALL or not plan.leg_plans:
                return cte_expr
            new_initial = self._apply_downstream_plan(cte_expr.initial_select_query, var, plan.leg_plans[0])
            assert isinstance(new_initial, (ast.SelectQuery, ast.SelectSetQuery))
            new_subsequent: list[ast.SelectSetNode] = []
            for i, node in enumerate(cte_expr.subsequent_select_queries):
                leg_plan = plan.leg_plans[i + 1]
                rewritten = self._apply_downstream_plan(node.select_query, var, leg_plan)
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

        # Add `first_alias.code_name AS code_name` to SELECT.
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
            for alias, _ in sources[1:]:
                predicate = ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=[first_alias, var.code_name]),
                    right=ast.Field(chain=[alias, var.code_name]),
                )
                cte_expr.where = self._append_and(cte_expr.where, predicate)

        return cte_expr

    @staticmethod
    def _append_and(existing: Optional[ast.Expr], new_predicate: ast.Expr) -> ast.Expr:
        """AND-flatten ``new_predicate`` into ``existing``, collapsing nested ``ast.And``."""
        if existing is None:
            return new_predicate
        if isinstance(existing, ast.And):
            return ast.And(exprs=[*list(existing.exprs), new_predicate])
        return ast.And(exprs=[existing, new_predicate])

    def _add_variable_columns(self, node: ast.SelectQuery, vars_for_context: list[MaterializableVariable]) -> None:
        """Add aliased variable columns to SELECT, update GROUP BY, and remove variable WHERE clauses."""
        select_additions = [self._create_column_field(var) for var in vars_for_context]
        if node.select:
            node.select = [*list(node.select), *select_additions]
        else:
            node.select = select_additions

        if node.group_by is not None or self._current_cte_name is None:
            self._add_group_by(node, vars_for_context)

        if node.where:
            node.where = self._remove_variable_from_where(node.where)

    def _add_cte_passthrough_columns(self, node: ast.SelectQuery, cte_vars: list[MaterializableVariable]) -> None:
        """Add passthrough columns + GROUP BY at top level for CTE-resident variables."""
        passthrough_additions: list[ast.Expr] = [ast.Field(chain=[var.code_name]) for var in cte_vars]
        if node.select:
            node.select = [*list(node.select), *passthrough_additions]
        else:
            node.select = passthrough_additions

        if node.group_by is not None or self._has_aggregate_functions(node):
            self._add_group_by(node, cte_vars, use_field_ref=True)

    @staticmethod
    def _has_aggregate_functions(node: ast.SelectQuery) -> bool:
        """Check if any SELECT expression uses an aggregate function (sum, count, avg, etc.)."""

        class AggFinder(TraversingVisitor):
            def __init__(self):
                super().__init__()
                self.found = False

            def visit_call(self, node: ast.Call):
                if _is_aggregate(node.name):
                    self.found = True
                else:
                    super().visit_call(node)

        finder = AggFinder()
        for expr in node.select or []:
            finder.visit(expr)
            if finder.found:
                return True
        return False

    def _vars_for_current_context(self) -> list[MaterializableVariable]:
        """Return variables that apply to the current CTE/top-level context."""
        return [v for v in self.variable_infos if v.cte_name == self._current_cte_name]

    def _add_group_by(
        self,
        node: ast.SelectQuery,
        vars_to_add: list[MaterializableVariable],
        use_field_ref: bool = False,
    ) -> None:
        """Add unique columns to GROUP BY, deduplicating by column_chain."""
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
                    group_by_additions.append(self._variable_expr(var))

        if node.group_by:
            node.group_by = [*list(node.group_by), *group_by_additions]
        elif group_by_additions:
            node.group_by = group_by_additions

    def _create_column_field(self, var: MaterializableVariable) -> ast.Expr:
        return ast.Alias(
            alias=var.code_name,
            expr=self._variable_expr(var),
        )

    @staticmethod
    def _variable_expr(var: MaterializableVariable) -> ast.Expr:
        """Expression used for the variable column without aliasing.

        Uses the original AST expression when available (e.g. for function calls
        like toDate(timestamp) that can't be reconstructed from column_chain).
        Always returns a fresh copy to avoid sharing AST nodes between SELECT and GROUP BY.
        When bucket_fn is set, wraps the column expression with the bucket function.
        """
        if var.column_ast is not None:
            base = CloningVisitor().visit(var.column_ast)
        else:
            base = ast.Field(chain=list(var.column_chain))

        if var.bucket_fn:
            return ast.Call(name=var.bucket_fn, args=[base])

        return base

    def _remove_variable_from_where(self, where_node: Optional[ast.Expr]) -> Optional[ast.Expr]:
        if where_node is None:
            return None

        if isinstance(where_node, ast.CompareOperation):
            return None if self._is_variable_comparison(where_node) else where_node

        if isinstance(where_node, ast.And):
            filtered_exprs = [
                expr
                for expr in where_node.exprs
                if not (isinstance(expr, ast.CompareOperation) and self._is_variable_comparison(expr))
            ]
            if not filtered_exprs:
                return None
            if len(filtered_exprs) == 1:
                return filtered_exprs[0]
            return ast.And(exprs=filtered_exprs)

        if isinstance(where_node, ast.Or):
            raise ValueError("Variables in OR conditions not supported")

        return where_node

    def _is_variable_comparison(self, node: ast.CompareOperation) -> bool:
        return any(self._expr_contains_variable(side) for side in (node.left, node.right))

    def _expr_contains_variable(self, node: ast.Expr) -> bool:
        if isinstance(node, ast.Placeholder) and node.chain and node.chain[0] == "variables":
            return True
        if isinstance(node, ast.Call):
            return any(self._expr_contains_variable(arg) for arg in node.args)
        return False
