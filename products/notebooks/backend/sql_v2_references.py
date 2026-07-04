"""Resolve SQLV2 node references by inlining upstream node queries as CTEs (Journey 3).

A SQLV2 node is a HogQL *query definition*, not a materialized frame. When one node
references another by its dataframe name — ``select … from df1 join df2`` — the whole
thing recomputes in ClickHouse with the referenced definitions inlined as CTEs
(decision 1 in the journey walkthroughs). We do that inlining here, once, at dispatch:
the run stores the self-contained query, so paging (a re-query of the same node) reuses
it verbatim and the data plane never has to know about references.

Only names the query actually reaches are inlined, transitively and in dependency order
(a CTE must be printed before the CTEs that use it). A name the query shadows with its
own ``WITH`` is left alone. Broken definitions that nothing references are never parsed,
so an unrelated malformed node can't fail a run.
"""

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_prepared_ast
from posthog.hogql.visitor import TraversingVisitor


class SQLV2ReferenceError(Exception):
    """A reference could not be resolved (cycle, or a referenced definition won't parse). User-facing."""


class _TableReferenceCollector(TraversingVisitor):
    """Collect the FROM/JOIN targets of a query that name one of `candidates`.

    Only bare single-identifier tables count — ``from df1`` matches, a column called
    ``df1`` does not — so a reference is a genuine table position, not any mention.
    """

    def __init__(self, candidates: set[str]) -> None:
        self.candidates = candidates
        self.found: set[str] = set()

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        table = node.table
        if isinstance(table, ast.Field) and len(table.chain) == 1 and table.chain[0] in self.candidates:
            name = table.chain[0]
            if isinstance(name, str):
                self.found.add(name)
        super().visit_join_expr(node)


def _references(query: ast.SelectQuery | ast.SelectSetQuery, candidates: set[str]) -> set[str]:
    collector = _TableReferenceCollector(candidates)
    collector.visit(query)
    # A name the query defines as its own CTE shadows the ref — don't pull it in.
    own_ctes = set(query.ctes.keys()) if isinstance(query, ast.SelectQuery) and query.ctes else set()
    return collector.found - own_ctes


def resolve_sql_v2_references(code: str, refs: dict[str, str]) -> str:
    """Return `code` with every referenced upstream definition inlined as a CTE.

    `refs` maps a node's dataframe name to its HogQL. Names not actually referenced by
    `code` (transitively) are ignored. Returns `code` unchanged when it references none
    of them, so a plain single-node run is byte-for-byte what the user wrote.

    Raises SQLV2ReferenceError on a reference cycle or an unparseable referenced
    definition; the caller surfaces the message on the run.
    """
    candidates = {name for name in refs if name}
    if not candidates:
        return code

    main = parse_select(code)
    if not _references(main, candidates):
        return code

    parsed: dict[str, ast.SelectQuery | ast.SelectSetQuery] = {}

    def parse_ref(name: str) -> ast.SelectQuery | ast.SelectSetQuery:
        if name not in parsed:
            try:
                parsed[name] = parse_select(refs[name])
            except ExposedHogQLError as exc:
                raise SQLV2ReferenceError(f"Referenced query '{name}' is invalid: {exc}") from exc
        return parsed[name]

    # Depth-first post-order so each CTE is emitted before the ones that use it; the GRAY
    # marker catches cycles (a name reached while still on the stack).
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {}
    order: list[str] = []

    def visit(name: str) -> None:
        color[name] = GRAY
        for dependency in sorted(_references(parse_ref(name), candidates)):
            if color.get(dependency) == GRAY:
                raise SQLV2ReferenceError(f"Reference cycle through '{dependency}'.")
            if color.get(dependency, WHITE) == WHITE:
                visit(dependency)
        color[name] = BLACK
        order.append(name)

    for start in sorted(_references(main, candidates)):
        if color.get(start, WHITE) == WHITE:
            visit(start)

    # The merged WITH hangs off a SelectQuery; wrap a top-level UNION so it can carry one.
    root = main if isinstance(main, ast.SelectQuery) else parse_select(f"select * from ({code})")
    if not isinstance(root, ast.SelectQuery):  # narrow for the type checker; the wrap is always a SelectQuery
        return code
    ctes: dict[str, ast.CTE] = dict(root.ctes or {})
    for name in order:
        # setdefault so the user's own CTE of the same name always wins over a node ref.
        ctes.setdefault(name, ast.CTE(name=name, expr=parse_ref(name), cte_type="subquery"))
    root.ctes = ctes

    return print_prepared_ast(root, context=HogQLContext(team_id=None), dialect="hogql")
