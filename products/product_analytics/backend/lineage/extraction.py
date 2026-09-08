import json
import hashlib
from collections.abc import Mapping, Sequence

from django.core.serializers.json import DjangoJSONEncoder

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import TraversingVisitor

_DATA_WAREHOUSE_NODE_KINDS = frozenset(
    {
        "DataWarehouseNode",
        "FunnelsDataWarehouseNode",
        "LifecycleDataWarehouseNode",
    }
)
_SKIPPED_KEYS = frozenset({"response", "results"})


def query_fingerprint(query: object) -> str:
    serialized = json.dumps(
        query,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        cls=DjangoJSONEncoder,
    )
    return hashlib.sha256(serialized.encode()).hexdigest()


def query_may_reference_data_models(query: object) -> bool:
    if isinstance(query, Mapping):
        kind = query.get("kind")
        if kind == "HogQLQuery" and not query.get("connectionId"):
            return isinstance(query.get("query"), str)
        if kind in _DATA_WAREHOUSE_NODE_KINDS or query.get("type") == "data_warehouse":
            return True
        return any(query_may_reference_data_models(child) for key, child in query.items() if key not in _SKIPPED_KEYS)
    if isinstance(query, Sequence) and not isinstance(query, (str, bytes, bytearray)):
        return any(query_may_reference_data_models(child) for child in query)
    return False


def extract_saved_query_names(query: object) -> set[str]:
    table_names: set[str] = set()
    _collect_table_names(query, table_names)
    return table_names


def _collect_table_names(value: object, table_names: set[str]) -> None:
    if isinstance(value, Mapping):
        kind = value.get("kind")
        if kind == "HogQLQuery" and not value.get("connectionId"):
            query = value.get("query")
            if isinstance(query, str) and query.strip():
                collector = _ScopedTableCollector()
                collector.visit(parse_select(query))
                table_names.update(collector.tables)
        elif kind in _DATA_WAREHOUSE_NODE_KINDS or value.get("type") == "data_warehouse":
            table_name = value.get("table_name")
            if isinstance(table_name, str) and table_name:
                table_names.add(table_name)

        for key, child in value.items():
            if key not in _SKIPPED_KEYS:
                _collect_table_names(child, table_names)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            _collect_table_names(child, table_names)


class _ScopedTableCollector(TraversingVisitor):
    """Collects the tables a query reads, with each CTE name hidden only inside its own scope.

    A non-recursive CTE body cannot see its own name, so `WITH orders AS (SELECT * FROM orders)
    SELECT * FROM orders` still reads the real `orders` table. Subtracting every CTE name from
    the whole query would drop that read and lose the dependency.
    """

    def __init__(self) -> None:
        self.tables: set[str] = set()
        self._cte_scopes: list[set[str]] = [set()]

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        scope = set(self._cte_scopes[-1])
        for cte_name, cte in (node.ctes or {}).items():
            self._cte_scopes.append(set(scope))
            self.visit(cte.expr)
            self._cte_scopes.pop()
            scope.add(cte_name)
        self._cte_scopes.append(scope)
        # The CTE bodies are visited above under their own scopes. Blank them so that the generic
        # traversal below does not visit them a second time under this wider scope.
        ctes, node.ctes = node.ctes, None
        try:
            super().visit_select_query(node)
        finally:
            node.ctes = ctes
            self._cte_scopes.pop()

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        if isinstance(node.table, ast.Field):
            chain = [str(part) for part in node.table.chain]
            if len(chain) != 1 or chain[0] not in self._cte_scopes[-1]:
                self.tables.add(".".join(chain))
        super().visit_join_expr(node)
