"""Result-envelope construction.

The envelope is the small JSON the sandbox POSTs to the backend callback:
`{status, columns, row_count, first_page, result_id, error?}`. It carries a
bounded preview only — never the full result (see sql_v2_result_delivery.md).
"""

import math
import uuid
import datetime
from typing import Any


def _json_cell(value: Any) -> Any:
    """Coerce an Arrow-produced cell into a JSON-safe value."""
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, datetime.datetime | datetime.date | datetime.time):
        return value.isoformat()
    if isinstance(value, bytes | bytearray):
        return value.decode("utf-8", "replace")
    if isinstance(value, list | tuple):
        return [_json_cell(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_cell(item) for key, item in value.items()}
    return str(value)


def json_safe_rows(rows: list[tuple[Any, ...]]) -> list[list[Any]]:
    return [[_json_cell(cell) for cell in row] for row in rows]


def from_columns_and_rows(
    columns: list[str],
    rows: list[tuple[Any, ...]],
    types: list[list[str]] | None = None,
    has_more: bool = False,
) -> dict[str, Any]:
    return {
        "status": "ok",
        "columns": columns,
        "types": types or [],
        "row_count": len(rows),
        "first_page": json_safe_rows(rows),
        "has_more": has_more,
        "result_id": str(uuid.uuid4()),
    }


def from_error(message: str) -> dict[str, Any]:
    return {"status": "error", "error": message}
