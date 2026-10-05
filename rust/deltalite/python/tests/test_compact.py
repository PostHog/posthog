"""Differential parity: `DeltaLiteTable.compact` against delta-rs `optimize.compact`.

Each case builds one fragmented table, copies it, and compacts one copy with each
implementation at the same target size. The two results must hold the same rows, the
same partitions with the same file counts, and output files whose Add statistics match
the Parquet they describe and match delta-rs's own statistics. The output is read back
through delta-rs, pyarrow (file by file) and DuckDB, and its Parquet schema must equal
the one delta-rs writes, so any reader of delta-rs's output can read deltalite's.
"""

from __future__ import annotations

import sys
import json
import shutil
import decimal
import datetime as dt
from pathlib import Path

import pytest

import duckdb
import pyarrow as pa
import deltalake
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.common import PARTITION_KEY, read_sorted, upsert_path  # noqa: E402

TARGET = 64 * 1024 * 1024


def frame(n: int, start: int, part: str | None, partitioned: bool = True, wide: bool = False) -> pa.Table:
    ids = list(range(start, start + n))
    cols: dict[str, pa.Array] = {
        "id": pa.array([f"id-{i:07d}" for i in ids], pa.string()),
        "n": pa.array([i if i % 7 else None for i in ids], pa.int64()),
        "f": pa.array([i / 3 for i in ids], pa.float64()),
        "flag": pa.array([i % 2 == 0 for i in ids], pa.bool_()),
        "ts": pa.array(
            [dt.datetime(2024, 1, 1, tzinfo=dt.UTC) + dt.timedelta(seconds=i) for i in ids],
            pa.timestamp("us", tz="UTC"),
        ),
        "day": pa.array([dt.date(2024, 1, 1) + dt.timedelta(days=i % 30) for i in ids], pa.date32()),
        "amount": pa.array([decimal.Decimal(i) / 100 for i in ids], pa.decimal128(18, 4)),
        "blob": pa.array([str(i).encode() for i in ids], pa.binary()),
        "tags": pa.array([[i, i + 1] if i % 5 else None for i in ids], pa.list_(pa.int64())),
        "obj": pa.array([{"a": i, "b": str(i)} for i in ids], pa.struct([("a", pa.int64()), ("b", pa.string())])),
        "payload": pa.array(
            [None if i % 3 == 0 else (f"{i}:" * (40_000 if wide else 24)) for i in ids],
            pa.string(),
        ),
    }
    if partitioned:
        cols[PARTITION_KEY] = pa.array([part] * n, pa.string())
    return pa.table(cols)


def append(uri: str, data: pa.Table, partitioned: bool, row_group: int | None = None) -> None:
    kwargs = {}
    if row_group:
        kwargs["writer_properties"] = deltalake.WriterProperties(max_row_group_size=row_group)
    deltalake.write_deltalake(
        uri,
        data,
        mode="append",
        partition_by=[PARTITION_KEY] if partitioned else None,
        **kwargs,
    )


def fragment(
    uri: str, parts: list[str] | None, files: int, rows: int, row_group: int | None = None, wide: bool = False
) -> None:
    """`files` appends of `rows` rows per partition (`parts=None`: unpartitioned)."""
    partitioned = parts is not None
    for f in range(files):
        for i, p in enumerate(parts or [None]):
            start = (i * files + f) * rows
            append(uri, frame(rows, start, p, partitioned, wide), partitioned, row_group)


def live_stats(uri: str) -> dict[tuple, list[dict]]:
    """The live files, grouped by partition values."""
    import deltalite

    out: dict[tuple, list[dict]] = {}
    for f in deltalite.DeltaLiteTable.open(uri).files():
        key = tuple(sorted(f["partition_values"].items()))
        out.setdefault(key, []).append(f)
    return out


def add_stats(uri: str) -> list[tuple[str, dict]]:
    """(path, parsed stats) of every live file, from the log."""
    dtab = deltalake.DeltaTable(uri)
    out = []
    for line_file in sorted((Path(uri) / "_delta_log").glob("*.json")):
        for line in line_file.read_text().splitlines():
            action = json.loads(line)
            if "add" in action:
                out.append((action["add"]["path"], json.loads(action["add"].get("stats") or "{}")))
            if "remove" in action:
                out = [(p, s) for p, s in out if p != action["remove"]["path"]]
    live = {Path(u).name for u in dtab.file_uris()}
    return [(p, s) for p, s in out if Path(p).name in live]


def assert_stats_describe_files(uri: str) -> None:
    """numRecords and nullCount of every live file match the Parquet it points at."""
    by_name = {Path(u).name: u for u in deltalake.DeltaTable(uri).file_uris()}
    for path, stats in add_stats(uri):
        table = pq.ParquetFile(by_name[Path(path).name]).read()
        assert stats["numRecords"] == table.num_rows, path
        for col, nulls in stats.get("nullCount", {}).items():
            if isinstance(nulls, dict):
                continue
            assert table.column(col).null_count == nulls, (path, col)
        for col, lo in stats.get("minValues", {}).items():
            if isinstance(lo, dict) or col == "payload":
                continue
            values = [v for v in table.column(col).to_pylist() if v is not None]
            if values and isinstance(lo, int | float):
                assert min(values) == lo, (path, col)


def compact_both(src: str, tmp: Path, **deltalite_kwargs) -> tuple[str, str, dict, dict]:
    import deltalite

    rs, dl = str(tmp / "delta_rs"), str(tmp / "deltalite")
    shutil.copytree(src, rs)
    shutil.copytree(src, dl)
    rs_metrics = deltalake.DeltaTable(rs).optimize.compact(target_size=TARGET)
    dl_stats = deltalite.DeltaLiteTable.open(dl).compact(target_file_size=TARGET, **deltalite_kwargs)
    return rs, dl, rs_metrics, dl_stats


def assert_parity(src: str, rs: str, dl: str, rs_metrics: dict, dl_stats: dict) -> None:
    before, schema_before = read_sorted(src)
    rows_rs, schema_rs = read_sorted(rs)
    rows_dl, schema_dl = read_sorted(dl)
    assert schema_dl == schema_rs == schema_before
    assert rows_dl == before, "deltalite changed the rows"
    assert rows_rs == before, "delta-rs changed the rows"

    assert dl_stats["numFilesRemoved"] == rs_metrics["numFilesRemoved"]
    assert dl_stats["numFilesAdded"] == rs_metrics["numFilesAdded"]
    assert dl_stats["partitionsOptimized"] == rs_metrics["partitionsOptimized"]
    assert dl_stats["totalConsideredFiles"] == rs_metrics["totalConsideredFiles"]
    assert dl_stats["totalFilesSkipped"] == rs_metrics["totalFilesSkipped"]

    layout_rs = {k: len(v) for k, v in live_stats(rs).items()}
    layout_dl = {k: len(v) for k, v in live_stats(dl).items()}
    assert layout_dl == layout_rs

    assert_stats_describe_files(dl)
    # Where each partition ends as one file, both writers saw the same rows, so the
    # order-independent statistics must agree exactly.
    stats_rs = dict(add_stats(rs))
    stats_dl = dict(add_stats(dl))
    by_part_rs = live_stats(rs)
    by_part_dl = live_stats(dl)
    for part, files in by_part_dl.items():
        if len(files) != 1 or len(by_part_rs[part]) != 1:
            continue
        s_dl = next(s for p, s in stats_dl.items() if Path(p).name == Path(files[0]["path"]).name)
        s_rs = next(s for p, s in stats_rs.items() if Path(p).name == Path(by_part_rs[part][0]["path"]).name)
        assert s_dl == s_rs, part

    # Other readers, and the physical Parquet schema delta-rs writes.
    con = duckdb.connect()
    con.execute("INSTALL delta; LOAD delta;")
    counts = [con.execute(f"SELECT count(*), count(DISTINCT id) FROM delta_scan('{u}')").fetchone() for u in (rs, dl)]
    assert counts[0] == counts[1]
    con.close()
    rs_files = [u for u in deltalake.DeltaTable(rs).file_uris() if ".zstd." in u]
    dl_files = [u for u in deltalake.DeltaTable(dl).file_uris() if ".zstd." in u]
    assert bool(rs_files) == bool(dl_files)
    for f in dl_files:
        pf = pq.ParquetFile(f)
        assert pf.schema.equals(pq.ParquetFile(rs_files[0]).schema), f
        assert pf.metadata.row_group(0).column(0).compression == "ZSTD"
        pf.read()

    history = deltalake.DeltaTable(dl).history(1)[0]
    if dl_stats["numFilesRemoved"]:
        assert history["operation"] == "OPTIMIZE"
        assert history["isBlindAppend"] is False
        assert history["operationMetrics"]["numFilesRemoved"] == dl_stats["numFilesRemoved"]


CASES = {
    "partitioned": {"parts": ["2024-01", "2024-02", "2024-03"], "files": 6, "rows": 200},
    "unpartitioned": {"parts": None, "files": 8, "rows": 300},
    "encoded_partition_values": {"parts": ["a b", "x/y", "50%", "ü", "k=v", "#?&"], "files": 3, "rows": 50},
    "multi_row_group_inputs": {"parts": ["p"], "files": 5, "rows": 1000, "row_group": 128},
    "wide_strings": {"parts": ["w"], "files": 4, "rows": 20, "wide": True},
}


@pytest.mark.parametrize("case", list(CASES))
def test_parity_with_delta_rs_optimize(tmp_path, case):
    spec = CASES[case]
    src = str(tmp_path / "src")
    fragment(src, spec["parts"], spec["files"], spec["rows"], spec.get("row_group"), spec.get("wide", False))
    rs, dl, rs_metrics, dl_stats = compact_both(src, tmp_path)
    assert dl_stats["numFilesRemoved"] > 0
    assert_parity(src, rs, dl, rs_metrics, dl_stats)


def test_parity_with_a_null_partition(tmp_path):
    src = str(tmp_path / "src")
    for f in range(4):
        data = pa.concat_tables([frame(30, f * 100, "a"), frame(30, f * 100 + 50, None)])
        append(src, data, True)
    rs, dl, rs_metrics, dl_stats = compact_both(src, tmp_path)
    assert dl_stats["partitions_compacted"] == 2
    assert_parity(src, rs, dl, rs_metrics, dl_stats)


def test_parity_after_a_partition_lost_every_file(tmp_path):
    src = str(tmp_path / "src")
    fragment(src, ["keep", "gone"], 4, 40)
    deltalake.DeltaTable(src).delete(f"{PARTITION_KEY} = 'gone'")
    rs, dl, rs_metrics, dl_stats = compact_both(src, tmp_path)
    assert dl_stats["partitions_compacted"] == 1
    assert_parity(src, rs, dl, rs_metrics, dl_stats)
    assert all(dict(k).get(PARTITION_KEY) != "gone" for k in live_stats(dl))


def test_parity_across_schema_evolution_and_upsert_history(tmp_path):
    """Files written before a column existed, and tombstones from deltalite upserts."""
    src = str(tmp_path / "src")
    fragment(src, ["p1", "p2"], 3, 50)
    deltalake.DeltaTable(src).alter.add_columns([deltalake.schema.Field("late", "string", nullable=True)])
    later = frame(20, 10_000, "p1").append_column("late", pa.array(["x"] * 20, pa.string()))
    append(src, later, True)
    update = frame(5, 0, "p1").append_column("late", pa.array(["u"] * 5, pa.string()))
    upsert_path(src, update, ["id"], PARTITION_KEY)
    rs, dl, rs_metrics, dl_stats = compact_both(src, tmp_path)
    assert_parity(src, rs, dl, rs_metrics, dl_stats)


def test_nothing_to_compact_commits_nothing(tmp_path):
    import deltalite

    src = str(tmp_path / "src")
    fragment(src, ["a", "b"], 1, 10)
    version = deltalake.DeltaTable(src).version()
    stats = deltalite.DeltaLiteTable.open(src).compact(target_file_size=TARGET)
    assert stats["files_removed"] == 0
    assert stats["commits"] == 0
    assert stats["version"] == version
    assert deltalake.DeltaTable(src).version() == version


def test_dry_run_and_partition_selection(tmp_path):
    import deltalite

    src = str(tmp_path / "src")
    fragment(src, ["big", "small"], 2, 10)
    fragment(src, ["big"], 6, 10)
    t = deltalite.DeltaLiteTable.open(src)
    version = t.version()
    plan = t.compact(target_file_size=TARGET, dry_run=True)
    assert (plan["dry_run"], plan["bins"], plan["files_removed"], plan["files_added"]) == (True, 2, 10, 0)
    # "small" would remove two files and write one: below the threshold.
    only_big = t.compact(target_file_size=TARGET, dry_run=True, min_partition_removable_files=2)
    assert (only_big["partitions_compacted"], only_big["files_removed"]) == (1, 8)
    named = t.compact(target_file_size=TARGET, dry_run=True, partitions=["small"])
    assert (named["files_considered"], named["files_removed"]) == (2, 2)
    assert deltalake.DeltaTable(src).version() == version

    stats = t.compact(target_file_size=TARGET, partitions=["small"], commit_metadata={"source": "test"})
    assert stats["files_removed"] == 2
    history = deltalake.DeltaTable(src).history(1)[0]
    assert history["source"] == "test"
    assert t.version() == version + 1


def test_deletion_vector_table_is_refused(tmp_path):
    import deltalite

    uri = str(tmp_path / "dv")
    deltalake.DeltaTable.create(
        uri,
        deltalake.Schema.from_arrow(frame(0, 0, "p").schema),
        partition_by=[PARTITION_KEY],
        configuration={"delta.enableDeletionVectors": "true"},
    )
    with pytest.raises(deltalite.DeltaLiteUnsupportedTableError, match="deletionVectors"):
        deltalite.DeltaLiteTable.open(uri).compact()
    assert deltalake.DeltaTable(uri).version() == 0


def test_column_mapping_table_is_refused(tmp_path):
    """A legacy-protocol column-mapping table, crafted by hand as in test_operations."""
    import deltalite

    uri = tmp_path / "cm"
    (uri / "_delta_log").mkdir(parents=True)
    field = {
        "name": "id",
        "type": "string",
        "nullable": True,
        "metadata": {"delta.columnMapping.id": 1, "delta.columnMapping.physicalName": "col-1"},
    }
    with open(uri / "_delta_log" / "00000000000000000000.json", "w") as f:
        f.write(json.dumps({"protocol": {"minReaderVersion": 2, "minWriterVersion": 5}}) + "\n")
        f.write(
            json.dumps(
                {
                    "metaData": {
                        "id": "11111111-1111-1111-1111-111111111111",
                        "format": {"provider": "parquet", "options": {}},
                        "schemaString": json.dumps({"type": "struct", "fields": [field]}),
                        "partitionColumns": [],
                        "configuration": {"delta.columnMapping.mode": "name", "delta.columnMapping.maxColumnId": "1"},
                        "createdTime": 1700000000000,
                    }
                }
            )
            + "\n"
        )
    with pytest.raises(deltalite.DeltaLiteUnsupportedTableError, match="columnMapping"):
        deltalite.DeltaLiteTable.open(str(uri)).compact()
