from typing import Any

import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.sources.github.github import (
    _make_webhook_dedupe_transformer,
)

_JOB_VERSION_KEYS = ["completed_at", "started_at", "created_at"]
_JOB_FIELDS: dict[str, pa.DataType] = {
    "id": pa.int64(),
    "status": pa.string(),
    "completed_at": pa.string(),
    "started_at": pa.string(),
    "created_at": pa.string(),
}
_JOB_SCHEMA = pa.schema(_JOB_FIELDS)


def _job(
    id: int, status: str, *, created: str, started: str | None = None, completed: str | None = None
) -> dict[str, Any]:
    return {"id": id, "status": status, "created_at": created, "started_at": started, "completed_at": completed}


def _dedupe(rows: list[dict[str, Any]], *, version_keys: list[str] = _JOB_VERSION_KEYS) -> list[dict[str, Any]]:
    table = pa.table({name: [row.get(name) for row in rows] for name in _JOB_SCHEMA.names}, schema=_JOB_SCHEMA)
    out = _make_webhook_dedupe_transformer("id", version_keys)(table)
    return [{name: out.column(name)[i].as_py() for name in out.column_names} for i in range(out.num_rows)]


def test_keeps_completed_when_whole_lifecycle_lands_in_one_batch() -> None:
    # The completed event is deliberately not last in the batch — ranking, not order, must win.
    rows = _dedupe(
        [
            _job(1, "queued", created="t0"),
            _job(1, "completed", created="t0", started="t1", completed="t2"),
            _job(1, "in_progress", created="t0", started="t1"),
        ]
    )
    assert rows == [_job(1, "completed", created="t0", started="t1", completed="t2")]


def test_keeps_newer_intermediate_event_when_neither_is_completed() -> None:
    # Both pre-completion (completed_at NULL): the later started_at must win, so a terminal-only
    # comparison wouldn't be enough — the full version tuple decides.
    rows = _dedupe(
        [
            _job(1, "in_progress", created="t0", started="t5"),
            _job(1, "in_progress", created="t0", started="t3"),
        ]
    )
    assert rows == [_job(1, "in_progress", created="t0", started="t5")]


def test_one_row_per_id_in_arrival_order() -> None:
    rows = _dedupe(
        [
            _job(1, "completed", created="a0", started="a1", completed="a2"),
            _job(2, "queued", created="b0"),
            _job(1, "queued", created="a0"),
        ]
    )
    assert [row["id"] for row in rows] == [1, 2]
    assert rows[0]["status"] == "completed"


def test_drops_rows_with_null_id() -> None:
    rows = _dedupe([{"id": None, "status": "queued", "created_at": "t0", "started_at": None, "completed_at": None}])
    assert rows == []


def test_equal_version_keys_keep_later_arrival() -> None:
    # GitHub's second-coarse updated_at can be identical for a fast in_progress -> completed
    # transition; the later-arriving completed event must win, so a strict > would freeze the row.
    table = pa.table(
        {
            "id": [1, 1],
            "status": ["in_progress", "completed"],
            "updated_at": ["2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"],
        }
    )
    out = _make_webhook_dedupe_transformer("id", ["updated_at"])(table)
    assert out.num_rows == 1
    assert out.column("status")[0].as_py() == "completed"


def test_single_version_key_keeps_max() -> None:
    # workflow_runs ranks on updated_at alone.
    table = pa.table(
        {
            "id": [1, 1],
            "status": ["in_progress", "completed"],
            "updated_at": ["2026-01-01T00:00:00Z", "2026-01-01T00:05:00Z"],
        }
    )
    out = _make_webhook_dedupe_transformer("id", ["updated_at"])(table)
    assert out.num_rows == 1
    assert out.column("status")[0].as_py() == "completed"


def test_returns_table_unchanged_when_version_columns_absent() -> None:
    table = pa.table({"id": [1, 1], "status": ["queued", "in_progress"]})
    out = _make_webhook_dedupe_transformer("id", _JOB_VERSION_KEYS)(table)
    assert out.num_rows == 2
