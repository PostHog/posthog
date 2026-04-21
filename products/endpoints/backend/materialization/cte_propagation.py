"""CTE variable propagation: graph helpers + downstream shape classifier.

When a variable lives inside a CTE and downstream CTEs read from it, the
materialized terminal table must still carry the variable column so the
read-time filter can slice rows per-variable-value. These helpers walk the
CTE reference graph, classify each downstream CTE's shape, and return a plan
object the transformer uses to rewrite SELECT / GROUP BY / WHERE.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from posthog.hogql import ast
from posthog.hogql.functions.mapping import HOGQL_AGGREGATIONS
from posthog.hogql.visitor import TraversingVisitor

from products.endpoints.backend.materialization.types import Rejection

# MULTI_JOIN propagation adds `a.var = b.var` to WHERE. Outer joins emit
# unmatched rows with NULL variable columns, which that predicate then drops
# — so only INNER/CROSS joins are safe.
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
    # (alias_or_cte_name, cte_name) pairs; empty for UNION_ALL where each leg has its own plan.
    propagating_sources: list[tuple[str, str]] = field(default_factory=list)
    leg_plans: list["DownstreamCTEPlan"] = field(default_factory=list)
    rejection: Optional[Rejection] = None


def _has_joins(node: ast.SelectQuery) -> bool:
    """Check if a SelectQuery has any JOINs (next_join on select_from)."""
    return node.select_from is not None and node.select_from.next_join is not None


class _CTEReferenceCollector(TraversingVisitor):
    """Collect names of sibling CTEs referenced anywhere in an expression subtree.

    A CTE reference appears as ``JoinExpr(table=Field(chain=["cte_name"]))``.
    Delegates to ``super().visit_join_expr`` so refs inside subqueries and further
    down the ``next_join`` chain are also caught.
    """

    def __init__(self, known_ctes: set[str]):
        super().__init__()
        self.known = known_ctes
        self.referenced: set[str] = set()

    def visit_join_expr(self, node: ast.JoinExpr):
        if isinstance(node.table, ast.Field) and len(node.table.chain) == 1:
            name = str(node.table.chain[0])
            if name in self.known:
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
) -> tuple[list[tuple[str, str]], Optional[Rejection]]:
    """Walk the top-level ``select_from`` chain, collecting propagating CTE refs.

    Returns ``(sources, rejection)``. ``rejection`` is non-None if any
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
                return [], Rejection.downstream_unsafe_join(cur.join_type)
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


def _emits_column(select_query: ast.SelectQuery, column_name: str) -> bool:
    for expr in select_query.select or []:
        name = _select_column_name(expr)
        if name == column_name:
            return True
    return False


def _select_has_aggregate(node: ast.SelectQuery) -> bool:
    """Return True if any SELECT expression in ``node`` uses a HogQL aggregate function."""
    agg_names = set(HOGQL_AGGREGATIONS.keys())

    class _AggFinder(TraversingVisitor):
        def __init__(self) -> None:
            super().__init__()
            self.found = False

        def visit_call(self, n: ast.Call) -> None:
            if n.name in agg_names:
                self.found = True
                return
            super().visit_call(n)

    finder = _AggFinder()
    for expr in node.select or []:
        finder.visit(expr)
        if finder.found:
            return True
    return False


def _reject(cte_name: str, shape: DownstreamCTEShape, rejection: Rejection) -> DownstreamCTEPlan:
    """Build a rejection DownstreamCTEPlan for a given shape."""
    return DownstreamCTEPlan(cte_name=cte_name, shape=shape, rejection=rejection)


def _classify_downstream_cte(
    cte_name: str,
    cte_expr: ast.Expr,
    propagating: set[str],
    code_names: list[str],
) -> DownstreamCTEPlan:
    """Classify a downstream CTE's shape; produce a plan or a Rejection."""

    if isinstance(cte_expr, ast.SelectSetQuery):
        non_union_legs = [node.set_operator for node in cte_expr.subsequent_select_queries]
        if any(op != "UNION ALL" for op in non_union_legs):
            return _reject(cte_name, DownstreamCTEShape.UNION_ALL, Rejection.union_not_all())

        leg_plans: list[DownstreamCTEPlan] = []
        for i, leg in enumerate(cte_expr.select_queries()):
            if not isinstance(leg, ast.SelectQuery):
                return _reject(cte_name, DownstreamCTEShape.UNION_ALL, Rejection.union_leg_nested_set_query())
            leg_plan = _classify_downstream_cte(f"{cte_name}#leg{i}", leg, propagating, code_names)
            if leg_plan.rejection is not None:
                return _reject(
                    cte_name,
                    DownstreamCTEShape.UNION_ALL,
                    Rejection.union_leg_failed(leg_plan.rejection),
                )
            if not leg_plan.propagating_sources and leg_plan.shape != DownstreamCTEShape.UNION_ALL:
                return _reject(
                    cte_name,
                    DownstreamCTEShape.UNION_ALL,
                    Rejection.union_leg_no_propagating_source(),
                )
            leg_plans.append(leg_plan)

        return DownstreamCTEPlan(
            cte_name=cte_name,
            shape=DownstreamCTEShape.UNION_ALL,
            leg_plans=leg_plans,
        )

    if not isinstance(cte_expr, ast.SelectQuery):
        return _reject(
            cte_name,
            DownstreamCTEShape.PROJECTION,
            Rejection.downstream_unsupported_body(type(cte_expr).__name__),
        )

    if cte_expr.window_exprs:
        return _reject(
            cte_name,
            DownstreamCTEShape.PROJECTION,
            Rejection.downstream_window_function(),
        )

    sources, rejection = _collect_propagating_sources_top_level(cte_expr.select_from, propagating)
    if rejection is not None:
        return _reject(cte_name, DownstreamCTEShape.PROJECTION, rejection)

    if _select_from_has_nested_reference(cte_expr.select_from, propagating):
        return _reject(
            cte_name,
            DownstreamCTEShape.PROJECTION,
            Rejection.downstream_nested_subquery_ref(),
        )

    if not sources:
        return _reject(
            cte_name,
            DownstreamCTEShape.PROJECTION,
            Rejection.downstream_no_propagating_source(),
        )

    for code_name in code_names:
        if _emits_column(cte_expr, code_name):
            return _reject(
                cte_name,
                DownstreamCTEShape.PROJECTION,
                Rejection.downstream_code_name_collision(code_name, cte_name),
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
