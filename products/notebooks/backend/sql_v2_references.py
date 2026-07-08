"""Resolve SQLV2 node references and route each run to its engine (Journeys 3–5).

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

Journey 5 adds **local** refs — frames a Python node bound in the kernel namespace. A
local frame cannot be pushed to ClickHouse, so a SQL node that references one runs in
the sandbox's DuckDB instead (`resolve_sql_node_run` decides per run), materializing
whatever HogQL refs it also reads — the same input shape Python nodes use.
"""

import re
import hashlib
from dataclasses import dataclass
from typing import Any

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_prepared_ast
from posthog.hogql.visitor import TraversingVisitor

from products.notebooks.backend.python_analysis import analyze_python_globals

# String literals ('' or backslash escapes) and comments, for the routing fallback to blank
# out before scanning: a frame name mentioned in a literal or comment must not trigger DuckDB
# routing. Double-quoted tokens are kept — in DuckDB those are quoted identifiers, i.e. real
# table references. An unbalanced literal simply doesn't match, degrading to the raw scan.
_SQL_LITERALS_AND_COMMENTS = re.compile(r"'(?:[^'\\]|\\.|'')*'|--[^\n]*|/\*.*?\*/", re.DOTALL)


class SQLV2ReferenceError(Exception):
    """A reference could not be resolved (cycle, or a referenced definition won't parse). User-facing."""


@dataclass(frozen=True)
class SQLV2Ref:
    """One upstream node available to a run, keyed by its dataframe name.

    kind "hogql" is a query definition (last_run_code holds its last-run, self-contained
    HogQL, or None if it has never completed a run); kind "local" is a frame a Python node
    bound in the kernel namespace — it has no query, only a name.
    """

    kind: str  # "hogql" | "local"
    last_run_code: str | None = None


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


def resolve_sql_v2_references(code: str, refs: dict[str, str | None]) -> str:
    """Return `code` with every referenced upstream definition inlined as a CTE.

    `refs` maps a node's dataframe name to its **last-run** HogQL — the exact query that
    produced the result the user is looking at — or None when that node has never
    completed a run. A name absent from `refs` (e.g. a real table like ``events``) is
    left untouched; a name present but None that `code` actually references raises,
    since there is no definition to join against yet.

    Names not actually referenced by `code` (transitively) are ignored. Returns `code`
    unchanged when it references none of them, so a plain single-node run is byte-for-byte
    what the user wrote.

    Raises SQLV2ReferenceError on a reference cycle, an unparseable referenced
    definition, or a referenced node that has not been run; the caller surfaces it.
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
            raw = refs[name]
            if raw is None or not raw.strip():
                raise SQLV2ReferenceError(f"Referenced node '{name}' has not been run yet — run it first.")
            try:
                parsed[name] = parse_select(raw)
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
    # The f-string embeds only `code`, already validated as HogQL by parse_select above; the
    # wrap is re-parsed here and printed via the AST printer, so no raw SQL reaches ClickHouse.
    # The newline before the closing paren keeps a trailing line comment (`-- …`) in the
    # user's query from swallowing the wrapper.
    # nosemgrep: semgrep.rules.security.hogql-fstring-audit
    root = main if isinstance(main, ast.SelectQuery) else parse_select(f"select * from ({code}\n)")
    if not isinstance(root, ast.SelectQuery):  # narrow for the type checker; the wrap is always a SelectQuery
        return code
    ctes: dict[str, ast.CTE] = dict(root.ctes or {})
    for name in order:
        # setdefault so the user's own CTE of the same name always wins over a node ref.
        ctes.setdefault(name, ast.CTE(name=name, expr=parse_ref(name), cte_type="subquery"))
    root.ctes = ctes

    return print_prepared_ast(root, context=HogQLContext(team_id=None), dialect="hogql")


def _hogql_input(name: str, ref: SQLV2Ref) -> dict[str, Any]:
    """The materialization spec for one HogQL ref: the executor fetches its last-run query to a
    local Arrow file keyed by query_hash, so an unchanged upstream reuses its frame."""
    if ref.last_run_code is None or not ref.last_run_code.strip():
        raise SQLV2ReferenceError(f"Referenced node '{name}' has not been run yet — run it first.")
    return {
        "name": name,
        "kind": "hogql",
        "query": ref.last_run_code,
        "query_hash": hashlib.sha256(ref.last_run_code.encode()).hexdigest(),
    }


def resolve_python_node_inputs(code: str, refs: dict[str, SQLV2Ref]) -> list[dict[str, Any]]:
    """Return the input specs for the upstream frames a Python node reads.

    A Python node references frames as plain variables, so only the names its code actually
    reads become inputs: a HogQL ref becomes a materialization spec (see `_hogql_input`); a
    local ref becomes a presence assertion — the frame already lives in the kernel namespace
    (bound by the upstream Python node), so the kernel just fails cleanly when it doesn't.

    Raises SQLV2ReferenceError if the code reads a HogQL node that has not been run yet.
    """
    used = set(analyze_python_globals(code).used)
    inputs: list[dict[str, Any]] = []
    for name, ref in refs.items():
        if not name or name not in used:
            continue
        if ref.kind == "local":
            inputs.append({"name": name, "kind": "local"})
        else:
            inputs.append(_hogql_input(name, ref))
    return inputs


def resolve_sql_node_run(code: str, refs: dict[str, SQLV2Ref]) -> tuple[str, str, list[dict[str, Any]]]:
    """Route a SQL node run to its engine; return (node_type, run_code, inputs).

    The routing rule from the journey walkthroughs (decision 1): a query whose referenced
    inputs are all HogQL definitions pushes to ClickHouse with the refs inlined as CTEs —
    `("hogql", inlined_code, [])`. A query that references any **local** frame (made by a
    Python node) cannot run in ClickHouse, so it runs in the sandbox's DuckDB instead —
    `("duckdb", code_as_written, inputs)`, where inputs materialize the HogQL refs it also
    reads (Journey 5: the join forces `df2` into the sandbox) and assert the local ones.

    Raises SQLV2ReferenceError for unrunnable refs, and lets the HogQL parser's own error
    surface for a malformed query that doesn't touch any local frame.
    """
    local_names = {name for name, ref in refs.items() if name and ref.kind == "local"}
    hogql_refs = {name: ref for name, ref in refs.items() if name and ref.kind == "hogql"}
    hogql_codes = {name: ref.last_run_code for name, ref in hogql_refs.items()}
    referenced_locals: set[str] = set()
    referenced_hogql: set[str] = set()
    if local_names:
        candidates = local_names | set(hogql_refs)
        try:
            found = _references(parse_select(code), candidates)
        except ExposedHogQLError:
            # DuckDB-only syntax can't parse as HogQL. If it names a local frame
            # (word-boundary match outside string literals and comments), route it to
            # DuckDB and let DuckDB report its own errors; otherwise fall through so
            # the HogQL path surfaces the parse error.
            searchable = _SQL_LITERALS_AND_COMMENTS.sub(" ", code)
            found = {name for name in candidates if re.search(rf"\b{re.escape(name)}\b", searchable)}
            if not found & local_names:
                found = set()
        referenced_locals = found & local_names
        referenced_hogql = found - local_names

    if not referenced_locals:
        return "hogql", resolve_sql_v2_references(code, hogql_codes), []

    inputs: list[dict[str, Any]] = []
    for name in sorted(referenced_locals | referenced_hogql):
        if name in local_names:
            inputs.append({"name": name, "kind": "local"})
        else:
            inputs.append(_hogql_input(name, hogql_refs[name]))
    return "duckdb", code, inputs
