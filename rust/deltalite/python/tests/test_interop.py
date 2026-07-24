"""Interop: do external readers see spec-compliant commits after a deltalite upsert?

Covers the Python `deltalake` package (which is what the rest of the pipeline uses) and
DuckDB's native `delta_scan` (a stand-in for the chdb/ClickHouse and Trino/Spark readers
that consume these tables in production).
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

import pytest

import duckdb
import pyarrow as pa
import deltalake

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.common import PARTITION_KEY, create_table, upsert_path  # noqa: E402


def simple(ids, part, v):
    n = len(ids)
    return pa.table(
        {
            "id": pa.array(ids, pa.string()),
            "v": pa.array([v] * n if isinstance(v, int) else v, pa.int64()),
            PARTITION_KEY: pa.array(part if isinstance(part, list) else [part] * n, pa.string()),
        }
    )


@pytest.fixture
def upserted(tmp_path):
    uri = str(tmp_path / "interop")
    create_table(uri, simple(["a", "b", "c"], "2026-07-23", 1), True)
    stats = upsert_path(
        uri,
        simple(["b", "d", "e"], ["2026-07-23", "2026-07-23", "2026-07-24"], 2),
        ["id"],
        PARTITION_KEY,
        {"run_uuid": "r", "batch_index": "0"},
    )
    return uri, stats


def test_python_deltalake_agrees_on_version_files_schema(upserted):
    import deltalite

    uri, stats = upserted
    py = deltalake.DeltaTable(uri)
    rs = deltalite.DeltaLiteTable.open(uri)

    assert py.version() == rs.version() == stats.version
    assert sorted(py.file_uris()) == sorted(rs.file_uris())
    assert py.schema().to_arrow() == rs.schema_arrow()
    assert py.metadata().partition_columns == rs.partition_columns()


def test_add_actions_carry_statistics(upserted):
    """Data skipping in external engines depends on Add-action stats being present."""
    uri, _ = upserted
    log_dir = Path(uri) / "_delta_log"
    latest = sorted(log_dir.glob("*.json"))[-1]

    adds = []
    for line in latest.read_text().splitlines():
        action = json.loads(line)
        if "add" in action:
            adds.append(action["add"])

    assert adds, "commit contained no Add actions"
    for add in adds:
        assert add.get("stats"), f"Add action missing stats: {add['path']}"
        stats = json.loads(add["stats"])
        assert stats["numRecords"] > 0
        assert "minValues" in stats and "maxValues" in stats
        assert "id" in stats["minValues"], "PK column missing from min/max stats"
        # Partition columns live in the path, not in the file stats.
        assert PARTITION_KEY not in stats["minValues"]


def test_duckdb_delta_scan_reads_the_table(upserted):
    """DuckDB reads the Delta log itself -- proves the commit is spec-compliant."""
    uri, _ = upserted
    con = duckdb.connect()
    con.execute("INSTALL delta; LOAD delta;")

    rows = con.execute(f"SELECT id, v, {PARTITION_KEY} FROM delta_scan('{uri}') ORDER BY id").fetchall()

    assert rows == [
        ("a", 1, "2026-07-23"),
        ("b", 2, "2026-07-23"),
        ("c", 1, "2026-07-23"),
        ("d", 2, "2026-07-23"),
        ("e", 2, "2026-07-24"),
    ]


def test_duckdb_sees_partition_pruning_metadata(upserted):
    uri, _ = upserted
    con = duckdb.connect()
    con.execute("INSTALL delta; LOAD delta;")
    n = con.execute(f"SELECT count(*) FROM delta_scan('{uri}') WHERE {PARTITION_KEY} = '2026-07-24'").fetchone()[0]
    assert n == 1


def test_tombstoned_files_are_not_read(upserted):
    """The rewritten file must be tombstoned, not merely superseded."""
    uri, stats = upserted
    assert stats.files_removed >= 1

    log_dir = Path(uri) / "_delta_log"
    latest = sorted(log_dir.glob("*.json"))[-1]
    removes = [json.loads(line)["remove"] for line in latest.read_text().splitlines() if "remove" in json.loads(line)]
    assert removes, "no Remove actions in the commit"
    for r in removes:
        assert r["dataChange"] is True
        assert r.get("deletionTimestamp")

    live = {Path(u).name for u in deltalake.DeltaTable(uri).file_uris()}
    for r in removes:
        assert Path(r["path"]).name not in live


def test_optimize_and_vacuum_still_work_after_upsert(upserted):
    """Maintenance stays on the Python package; it must accept deltalite's commits."""
    uri, _ = upserted
    dt = deltalake.DeltaTable(uri)
    dt.optimize.compact()
    dt = deltalake.DeltaTable(uri)
    dt.vacuum(retention_hours=0, enforce_retention_duration=False, dry_run=False)

    rows = deltalake.DeltaTable(uri).to_pyarrow_table().sort_by("id")["v"].to_pylist()
    assert rows == [1, 2, 1, 2, 2]
