import json
import hashlib
from collections.abc import Mapping, Sequence

from django.core.serializers.json import DjangoJSONEncoder

from posthog.hogql.metadata import get_table_names
from posthog.hogql.parser import parse_select

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
                table_names.update(get_table_names(parse_select(query)))
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
