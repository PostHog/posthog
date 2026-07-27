"""Helpers for pulling CH-side metrics out of `system.query_log`.

Both backends tag candidate SQL with an ``autoresearch_run_id`` in the
``log_comment`` JSON, then look the row up in ``system.query_log`` to get the
authoritative ``query_duration_ms`` / ``read_rows`` / ``read_bytes`` / ``query_id``.
The lookup SQL and parsing live here so the metabase- and local-CH-specific
``run()`` paths share their shape.
"""

from __future__ import annotations

import re
from typing import Any

# Run-id format check: 16 hex chars (``uuid.uuid4().hex[:16]``). The match is
# load-bearing — the run id is interpolated into the lookup SQL as a
# string-literal value, and limiting it to ``[0-9a-f]`` means it can't escape
# the quotes regardless of how it was generated.
_RUN_ID_RE = re.compile(r"[0-9a-f]{16}")


def is_valid_run_id(run_id: str) -> bool:
    return bool(_RUN_ID_RE.fullmatch(run_id))


def build_lookup_sql(run_id: str, *, table_expr: str) -> str | None:
    """Return the SELECT to find ``run_id``'s QueryFinish row, or ``None`` if invalid.

    ``table_expr`` is the ClickHouse table reference for ``query_log`` — the
    test cluster wants ``clusterAllReplicas(posthog, system, query_log)`` to
    cover all shards; a single-node dev CH wants ``system.query_log``. The
    column shape is the same on both.
    """
    if not is_valid_run_id(run_id):
        return None
    return (
        "SELECT query_duration_ms, read_rows, read_bytes, query_id "
        f"FROM {table_expr} "
        "WHERE event_date >= today() - 1 "
        "AND type = 'QueryFinish' "
        f"AND JSONExtractString(log_comment, 'autoresearch_run_id') = '{run_id}' "
        "ORDER BY event_time DESC LIMIT 1"
    )


def parse_lookup_row(row: list[Any]) -> tuple[float, int, int, str] | None:
    """Coerce one query_log result row into (duration_ms, rows_read, bytes_read, query_id).

    Returns ``None`` if the row is malformed (wrong arity, non-numeric timing).
    """
    if len(row) != 4:
        return None
    duration_ms, rows_read, bytes_read, query_id = row
    try:
        return float(duration_ms), int(rows_read), int(bytes_read), str(query_id)
    except (TypeError, ValueError):
        return None
