"""Client for the backend data plane — the sandbox's only read path to PostHog data.

POSTs a HogQL query to the backend's data-plane endpoint (authed with the
run-scoped data-plane token) and decodes the Arrow stream response. Uses urllib
so the only third-party dependency is pyarrow (present in the sandbox image).
"""

import json
import urllib.error
import urllib.request
from typing import Any

import pyarrow as pa

_REQUEST_TIMEOUT_SECONDS = 120


class DataPlaneError(Exception):
    """A query the data plane rejected or failed to run; message is user-facing."""


def fetch_query_page(
    url: str, token: str, query: str, limit: int, offset: int = 0
) -> tuple[list[str], list[tuple[Any, ...]], list[list[str]]]:
    """Run `query` through the data plane; return (columns, rows, types) of the capped page."""
    request = urllib.request.Request(
        url,
        data=json.dumps({"query": query, "limit": limit, "offset": offset}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            return decode_arrow_stream(response)
    except urllib.error.HTTPError as exc:
        raise DataPlaneError(_error_detail(exc)) from exc
    except urllib.error.URLError as exc:
        raise DataPlaneError(f"Could not reach the data plane: {exc.reason}") from exc
    except pa.ArrowInvalid as exc:
        raise DataPlaneError(f"Invalid Arrow response from the data plane: {exc}") from exc


def decode_arrow_stream(source: Any) -> tuple[list[str], list[tuple[Any, ...]], list[list[str]]]:
    """Decode an Arrow IPC stream (file-like or bytes-like) into (columns, rows, types).

    Types come from the `hogql_types` schema metadata the data plane attaches (the
    real ClickHouse type names); when absent they are approximated from the Arrow
    schema so the envelope always carries something usable for axis detection.
    """
    table = pa.ipc.open_stream(source).read_all()
    columns = table.column_names
    # Columnar → row tuples without to_pylist(), which would collapse duplicate column names.
    column_values = [table.column(i).to_pylist() for i in range(table.num_columns)]
    rows = list(zip(*column_values)) if column_values else []

    metadata = table.schema.metadata or {}
    raw_types = metadata.get(b"hogql_types")
    if raw_types:
        try:
            types = [[str(name), str(type_name)] for name, type_name in json.loads(raw_types)]
        except (json.JSONDecodeError, ValueError, TypeError):
            types = _types_from_arrow_schema(table.schema)
    else:
        types = _types_from_arrow_schema(table.schema)
    return columns, rows, types


def _types_from_arrow_schema(schema: Any) -> list[list[str]]:
    def type_name(arrow_type: Any) -> str:
        if pa.types.is_boolean(arrow_type):
            return "Bool"
        if pa.types.is_integer(arrow_type):
            return "Int64"
        if pa.types.is_floating(arrow_type) or pa.types.is_decimal(arrow_type):
            return "Float64"
        if pa.types.is_timestamp(arrow_type):
            return "DateTime"
        if pa.types.is_date(arrow_type):
            return "Date"
        return "String"

    return [[field.name, type_name(field.type)] for field in schema]


def _error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        body = json.loads(exc.read().decode("utf-8", "replace"))
        detail = body.get("error")
        if isinstance(detail, str) and detail:
            return detail
    except (json.JSONDecodeError, ValueError, OSError):
        pass
    return f"Data plane request failed with HTTP {exc.code}"
