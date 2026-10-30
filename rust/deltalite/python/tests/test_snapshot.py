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
import pyarrow.compute as pc

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


def stat_rows(ids: list[int], names: list[str | None], part: str) -> pa.Table:
    return pa.table(
        {
            "id": pa.array(ids, pa.int64()),
            "name": pa.array(names, pa.string()),
            "seen_at": pa.array([1_700_000_000_000_000 + i * 1_000_000 for i in ids], pa.timestamp("us")),
            "blank": pa.array([None] * len(ids), pa.string()),
            PARTITION_KEY: pa.array([part] * len(ids), pa.string()),
        }
    )


def folded_in_python(dt: deltalake.DeltaTable, columns: list[str]) -> dict:
    """The fold over delta-rs's per-file projection, the way a pyarrow caller computes it."""
    actions = pa.table(dt.get_add_actions(flatten=True))
    out = {"num_files": actions.num_rows, "num_records": pc.sum(actions["num_records"]).as_py()}
    for column in columns:
        out[f"null_count.{column}"] = pc.sum(actions[f"null_count.{column}"]).as_py()
        out[f"min.{column}"] = pc.min_max(actions[f"min.{column}"])["min"].as_py()
        out[f"max.{column}"] = pc.min_max(actions[f"max.{column}"])["max"].as_py()
    return out


@pytest.mark.parametrize("partitioned", [False, True], ids=["unpartitioned", "partitioned"])
def test_add_action_stats_fold_the_per_file_projection(tmp_path, partitioned):
    import deltalite

    uri = str(tmp_path / "t")
    create_table(uri, stat_rows([5, 6], ["pear", None], "p1"), partitioned=partitioned)
    for batch in (stat_rows([1, 2, 3], ["apple", "zebra", None], "p2"), stat_rows([9], [None], "p1")):
        deltalake.write_deltalake(uri, batch, mode="append", partition_by=[PARTITION_KEY] if partitioned else None)

    rs = deltalite.DeltaLiteTable.open(uri)
    dt = deltalake.DeltaTable(uri)
    # Unpartitioned, the partition key is an ordinary string column and carries statistics.
    columns = ["id", "name", "seen_at", "blank"] + ([] if partitioned else [PARTITION_KEY])
    projection = pa.table(dt.get_add_actions(flatten=True))

    stats = rs.add_action_stats()
    assert stats.num_rows == 1
    row = stats.to_pylist()[0]
    assert row == folded_in_python(dt, columns)
    assert row["num_files"] == 3
    assert row["num_records"] == 6
    assert (row["min.id"], row["max.id"], row["null_count.id"]) == (1, 9, 0)
    assert (row["min.name"], row["max.name"], row["null_count.name"]) == ("apple", "zebra", 3)
    assert (row["min.blank"], row["max.blank"], row["null_count.blank"]) == (None, None, 6)
    for column in columns:
        assert stats.schema.field(f"min.{column}").type == projection.schema.field(f"min.{column}").type
    if partitioned:
        # A partition column has no per-file statistics, so it gets no fields.
        assert not [name for name in stats.schema.names if name.endswith(PARTITION_KEY)]

    subset = rs.add_action_stats(columns=["seen_at", "no_such_column"])
    assert subset.schema.names == ["num_files", "num_records", "null_count.seen_at", "min.seen_at", "max.seen_at"]
    assert subset.to_pylist()[0] == {k: row[k] for k in subset.schema.names}


def test_add_action_stats_of_an_empty_table_count_zero_files(tmp_path):
    import deltalite

    uri = str(tmp_path / "t")
    deltalake.DeltaTable.create(uri, pa.schema([("id", pa.int64()), ("name", pa.string())]))

    row = deltalite.DeltaLiteTable.open(uri).add_action_stats().to_pylist()[0]
    assert row["num_files"] == 0
    assert row["num_records"] is None
    assert all(value is None for key, value in row.items() if key != "num_files")
