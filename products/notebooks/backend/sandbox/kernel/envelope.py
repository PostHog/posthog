"""Result-envelope construction.

The envelope is the small JSON the sandbox POSTs to the backend callback:
`{status, columns, row_count, first_page, result_id, error?}`. It carries a
bounded preview only — never the full result (see sql_v2_result_delivery.md).
"""

import math
import uuid
import datetime
from collections.abc import Sequence
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


def json_safe_rows(rows: Sequence[Sequence[Any]]) -> list[list[Any]]:
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


INTERRUPTED_MESSAGE = "Run interrupted."


def as_interrupted(result: dict[str, Any]) -> dict[str, Any]:
    """Rewrite a non-ok envelope as the interrupted outcome, keeping any captured output.

    The underlying error is almost always the interrupt itself (KeyboardInterrupt, an
    aborted data-plane wait), so the user-facing message is the interrupt, not the symptom.
    """
    return {**result, "status": "interrupted", "error": INTERRUPTED_MESSAGE}


def from_python_execution(
    *,
    status: str,
    stdout: str = "",
    stderr: str = "",
    error: str | None = None,
    columns: list[str] | None = None,
    types: list[list[str]] | None = None,
    rows: Sequence[Sequence[Any]] | None = None,
    row_count: int = 0,
    has_more: bool = False,
    media: list[dict[str, str]] | None = None,
    result_id: str | None = None,
) -> dict[str, Any]:
    """Envelope for a Python node run.

    Carries the captured stdout/stderr and any matplotlib images alongside the bounded
    table preview. `row_count` is the produced frame's full size (not len(rows), which is
    only the previewed page); `result_id` keys the on-disk frame for later paging.
    """
    envelope: dict[str, Any] = {
        "status": status,
        "stdout": stdout,
        "stderr": stderr,
        "columns": columns or [],
        "types": types or [],
        "row_count": row_count,
        "first_page": json_safe_rows(rows or []),
        "has_more": has_more,
        "media": media or [],
    }
    if error is not None:
        envelope["error"] = error
    if result_id is not None:
        envelope["result_id"] = result_id
    return envelope
