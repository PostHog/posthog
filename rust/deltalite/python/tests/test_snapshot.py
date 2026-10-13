"""Snapshot reads served from the deltalite handle's in-memory state.

A writer that already holds a `DeltaLiteTable` should not need a second delta-rs
`DeltaTable` open to learn the table's identity, schema or live files. These tests hold
the handle's answers to what delta-rs reports for the same table, and check they follow
the handle's own commits.
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

import pytest

import pyarrow as pa
import deltalake

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.common import PARTITION_KEY, create_table  # noqa: E402


def rows(ids: list[int], part: list[str] | None = None) -> pa.Table:
    return pa.table(
        {
            "id": pa.array(ids, pa.int64()),
            "v": pa.array([i * 10 for i in ids], pa.int64()),
            PARTITION_KEY: pa.array(part or ["p1"] * len(ids), pa.string()),
        }
    )


def add_actions_by_path(dt: deltalake.DeltaTable) -> dict[str, dict]:
    """delta-rs's view of the live files, keyed by path (it returns an arro3 table)."""
    actions = pa.table(dt.get_add_actions(flatten=False)).to_pylist()
    return {a["path"]: a for a in actions}


@pytest.mark.parametrize("partitioned", [False, True], ids=["unpartitioned", "partitioned"])
def test_snapshot_reads_match_delta_rs(tmp_path, partitioned):
    import deltalite

    uri = str(tmp_path / "t")
    create_table(uri, rows([1, 2, 3, 4], ["p1", "p1", "p2", "p2"]), partitioned=partitioned)

    rs = deltalite.DeltaLiteTable.open(uri)
    dt = deltalake.DeltaTable(uri)

    assert rs.version() == dt.version()
    assert rs.table_id() == dt.metadata().id
    assert rs.configuration() == dt.metadata().configuration
    assert json.loads(rs.schema_json()) == json.loads(dt.schema().to_json())

    expected = add_actions_by_path(dt)
    assert rs.num_files() == len(expected)
    files = rs.files()
    assert sorted(f["path"] for f in files) == sorted(expected)
    for f in files:
        action = expected[f["path"]]
        assert f["size"] == action["size_bytes"]
        assert f["modification_time"] == action["modification_time"]
        if partitioned:
            assert f["partition_values"] == action["partition"]
            assert f["path"].startswith(f"{PARTITION_KEY}={f['partition_values'][PARTITION_KEY]}/")
        else:
            assert f["partition_values"] == {}


def test_files_follow_the_handles_own_commit(tmp_path):
    import deltalite

    uri = str(tmp_path / "t")
    create_table(uri, rows([1, 2], ["p1", "p1"]), partitioned=True)

    rs = deltalite.DeltaLiteTable.open(uri)
    before = {f["path"] for f in rs.files()}
    stats = rs.upsert(rows([3], ["p2"]), primary_keys=["id"], partition_key=PARTITION_KEY)

    assert rs.version() == stats.version
    after = {f["path"] for f in rs.files()}
    assert before < after, "the new partition's file must appear without a reload"
    assert sorted(after) == sorted(add_actions_by_path(deltalake.DeltaTable(uri)))


def test_initial_open_is_reported_on_the_first_upsert_only(tmp_path):
    import deltalite

    uri = str(tmp_path / "t")
    create_table(uri, rows([1, 2]), partitioned=False)

    rs = deltalite.DeltaLiteTable.open(uri)
    first = rs.upsert(rows([1]), primary_keys=["id"])
    second = rs.upsert(rows([2]), primary_keys=["id"])

    assert isinstance(first.initial_open_ms, int)
    assert second.initial_open_ms == 0
