"""Mixed-writer operation sequences: everything EXCEPT the upsert stays on the Python
`deltalake` package. These tests interleave the two writers against the same table and
assert correct contents and a valid, readable log at every step.

Covers: create/append/overwrite via Python + upsert via deltalite, optimize.compact,
vacuum, alter.add_columns, history/idempotency metadata interleaving, the
partition-downgrade rule, and refusal of deletion-vector / column-mapping tables.
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
from harness.common import PARTITION_KEY, create_table, merge_path, read_sorted, upsert_path  # noqa: E402


def simple(ids, part, v, extra="ABSENT"):
    n = len(ids)
    d = {
        "id": pa.array(ids, pa.string()),
        "v": pa.array([v] * n if isinstance(v, int) else v, pa.int64()),
        PARTITION_KEY: pa.array(part if isinstance(part, list) else [part] * n, pa.string()),
    }
    if extra != "ABSENT":
        d["new_col"] = pa.array(extra, pa.string())
    return pa.table(d)


def content(uri) -> dict[tuple[str | None, str], int]:
    """{(id, partition): v} via the Python package -- also proves the log is readable."""
    tbl = deltalake.DeltaTable(uri).to_pyarrow_table()
    return dict(
        zip(
            zip(tbl["id"].to_pylist(), tbl[PARTITION_KEY].to_pylist()),
            tbl["v"].to_pylist(),
        )
    )


def duckdb_content(uri) -> dict[tuple[str | None, str], int]:
    con = duckdb.connect()
    con.execute("INSTALL delta; LOAD delta;")
    rows = con.execute(f"SELECT id, {PARTITION_KEY}, v FROM delta_scan('{uri}')").fetchall()
    con.close()
    return {(r[0], r[1]): r[2] for r in rows}


def assert_valid_log(uri, expected: dict) -> None:
    """Content matches via the Python reader AND the version chain is contiguous."""
    assert content(uri) == expected
    log_dir = Path(uri) / "_delta_log"
    versions = sorted(int(p.stem) for p in log_dir.glob("*.json"))
    assert versions == list(range(versions[0], versions[-1] + 1))
    assert deltalake.DeltaTable(uri).version() == versions[-1]


# --------------------------------------------------------------------------------------
# 1. Interleaved sequences
# --------------------------------------------------------------------------------------


def test_interleaved_create_append_upsert_optimize_vacuum(tmp_path):
    """create (py) -> append (py) -> upsert -> append (py) -> upsert -> compact (py)
    -> upsert -> vacuum (py) -> upsert, asserting contents + valid log at every step."""
    uri = str(tmp_path / "lifecycle")
    p = "2026-07-23"

    # create (python) -- empty partitioned table, as the helper's first-sync path does
    deltalake.DeltaTable.create(
        uri,
        deltalake.Schema.from_arrow(simple([], p, [])[:0].schema),
        partition_by=[PARTITION_KEY],
    )
    expected: dict = {}
    assert_valid_log(uri, expected)

    # append (python)
    deltalake.write_deltalake(uri, simple(["a", "b"], p, 1), mode="append")
    expected = {("a", p): 1, ("b", p): 1}
    assert_valid_log(uri, expected)

    # upsert (deltalite) into a table whose only files were written by python
    upsert_path(uri, simple(["b", "c"], p, 2), ["id"], PARTITION_KEY)
    expected.update({("b", p): 2, ("c", p): 2})
    assert_valid_log(uri, expected)

    # append (python) on top of deltalite's files
    deltalake.write_deltalake(uri, simple(["d"], p, 3), mode="append")
    expected[("d", p)] = 3
    assert_valid_log(uri, expected)

    # upsert must replace rows living in BOTH writers' files in one pass
    upsert_path(uri, simple(["a", "d", "e"], p, 4), ["id"], PARTITION_KEY)
    expected.update({("a", p): 4, ("d", p): 4, ("e", p): 4})
    assert_valid_log(uri, expected)

    # a second small file, so compaction has real work to do
    deltalake.write_deltalake(uri, simple(["f0"], p, 3), mode="append")
    expected[("f0", p)] = 3
    assert len(deltalake.DeltaTable(uri).file_uris()) >= 2

    # compact (python)
    metrics = deltalake.DeltaTable(uri).optimize.compact()
    assert metrics["numFilesRemoved"] > 0, "expected real compaction work"
    assert_valid_log(uri, expected)

    # upsert after compact
    upsert_path(uri, simple(["e", "f"], p, 5), ["id"], PARTITION_KEY)
    expected.update({("e", p): 5, ("f", p): 5})
    assert_valid_log(uri, expected)

    # vacuum (python), production settings
    deltalake.DeltaTable(uri).vacuum(retention_hours=0, enforce_retention_duration=False, dry_run=False)
    assert_valid_log(uri, expected)

    # upsert after vacuum
    upsert_path(uri, simple(["a", "g"], p, 6), ["id"], PARTITION_KEY)
    expected.update({("a", p): 6, ("g", p): 6})
    assert_valid_log(uri, expected)

    # an external reader agrees with the final state
    assert duckdb_content(uri) == expected


def test_full_refresh_overwrite_then_upsert_then_overwrite(tmp_path):
    """The full-refresh path (`mode="overwrite", schema_mode="overwrite"`) must wipe
    deltalite's rows, and upsert must work on the overwritten table -- both ways round."""
    uri = str(tmp_path / "refresh")
    p = "2026-07-23"
    create_table(uri, simple(["a", "b"], p, 1), True)

    upsert_path(uri, simple(["b", "c"], p, 2), ["id"], PARTITION_KEY)
    assert content(uri) == {("a", p): 1, ("b", p): 2, ("c", p): 2}

    # full refresh: overwrite replaces everything, including deltalite-written files
    deltalake.write_deltalake(
        uri,
        simple(["x", "y"], p, 10),
        partition_by=[PARTITION_KEY],
        mode="overwrite",
        schema_mode="overwrite",
    )
    assert content(uri) == {("x", p): 10, ("y", p): 10}

    # upsert on the overwritten table
    upsert_path(uri, simple(["y", "z"], p, 11), ["id"], PARTITION_KEY)
    expected = {("x", p): 10, ("y", p): 11, ("z", p): 11}
    assert_valid_log(uri, expected)

    # and overwrite again on top of that
    deltalake.write_deltalake(
        uri,
        simple(["q"], p, 20),
        partition_by=[PARTITION_KEY],
        mode="overwrite",
        schema_mode="overwrite",
    )
    assert_valid_log(uri, {("q", p): 20})


def test_overwrite_with_changed_schema_then_upsert(tmp_path):
    """schema_mode="overwrite" may change the column set; upsert must follow the new
    schema, not the one deltalite last wrote."""
    uri = str(tmp_path / "reschema")
    p = "2026-07-23"
    create_table(uri, simple(["a"], p, 1), True)
    upsert_path(uri, simple(["b"], p, 2), ["id"], PARTITION_KEY)

    replaced = pa.table(
        {
            "id": pa.array(["m"], pa.string()),
            "brand_new": pa.array([7], pa.int64()),
            PARTITION_KEY: pa.array([p], pa.string()),
        }
    )
    deltalake.write_deltalake(uri, replaced, partition_by=[PARTITION_KEY], mode="overwrite", schema_mode="overwrite")

    batch = pa.table(
        {
            "id": pa.array(["m", "n"], pa.string()),
            "brand_new": pa.array([8, 9], pa.int64()),
            PARTITION_KEY: pa.array([p, p], pa.string()),
        }
    )
    upsert_path(uri, batch, ["id"], PARTITION_KEY)

    tbl = deltalake.DeltaTable(uri).to_pyarrow_table().sort_by("id")
    assert tbl.schema.names == ["id", "brand_new", PARTITION_KEY]
    assert tbl["brand_new"].to_pylist() == [8, 9]


def test_upsert_add_columns_upsert_with_and_without_new_column(tmp_path):
    """upsert -> alter.add_columns (py) -> upsert WITH the new column -> upsert WITHOUT
    it. Pins deltalite's behavior on the last step (missing column -> NULL on updated
    rows); the divergence from raw MERGE is documented in the test below."""
    uri = str(tmp_path / "evolve")
    p = "2026-07-23"
    create_table(uri, simple(["a", "b"], p, 1), True)

    upsert_path(uri, simple(["b", "c"], p, 2), ["id"], PARTITION_KEY)

    # additive evolution via the python package (upsert_path's evolve_schema does the
    # same alter.add_columns call the production helper does)
    upsert_path(uri, simple(["c", "d"], p, 3, extra=["C", "D"]), ["id"], PARTITION_KEY)
    tbl = deltalake.DeltaTable(uri).to_pyarrow_table().sort_by("id")
    assert tbl["new_col"].to_pylist() == [None, None, "C", "D"]

    # batch WITHOUT the new column: the updated row's new_col becomes NULL (wholesale
    # row replacement with a null-padded source), inserted rows get NULL too
    upsert_path(uri, simple(["d", "e"], p, 4), ["id"], PARTITION_KEY)
    tbl = deltalake.DeltaTable(uri).to_pyarrow_table().sort_by("id")
    assert tbl["id"].to_pylist() == ["a", "b", "c", "d", "e"]
    assert tbl["v"].to_pylist() == [1, 2, 3, 4, 4]
    assert tbl["new_col"].to_pylist() == [None, None, "C", None, None]


def test_missing_column_after_evolution_diverges_from_raw_merge(tmp_path):
    """FINDING (executable): for a source batch MISSING a recently-added column,
    `when_matched_update_all` only assigns columns present in the source, so raw MERGE
    PRESERVES the target's existing value -- while deltalite null-pads the source and
    replaces the row wholesale, WIPING it to NULL.

    Production pads batches to the table schema (`evolve_pyarrow_schema`) before
    writing, and against a null-PADDED source the two paths agree (asserted below), so
    the divergence is only reachable if a caller bypasses the padding preamble.
    """
    p = "2026-07-23"

    def run(path, uri, pad_missing):
        create_table(uri, simple(["a"], p, 1), True)
        path(uri, simple(["a"], p, 2, extra=["A"]), ["id"], PARTITION_KEY)
        missing = (
            simple(["a"], p, 3, extra=[None])  # padded, as production does
            if pad_missing
            else simple(["a"], p, 3)  # column absent
        )
        path(uri, missing, ["id"], PARTITION_KEY)
        return deltalake.DeltaTable(uri).to_pyarrow_table()["new_col"].to_pylist()

    # column absent: raw MERGE keeps 'A', deltalite wipes to NULL -- the divergence
    assert run(merge_path, str(tmp_path / "m_absent"), False) == ["A"]
    assert run(upsert_path, str(tmp_path / "u_absent"), False) == [None]

    # column present-but-null (the production shape): both wipe to NULL -- parity
    assert run(merge_path, str(tmp_path / "m_padded"), True) == [None]
    assert run(upsert_path, str(tmp_path / "u_padded"), True) == [None]


def test_merge_then_upsert_then_merge_same_table(tmp_path):
    """The rollout is flag-gated: a table may see MERGE and deltalite commits
    interleaved. Both must read each other's files correctly."""
    uri = str(tmp_path / "mixed_writers")
    p = "2026-07-23"
    create_table(uri, simple(["a", "b"], p, 1), True)

    merge_path(uri, simple(["b", "c"], p, 2), ["id"], PARTITION_KEY)
    upsert_path(uri, simple(["c", "d"], p, 3), ["id"], PARTITION_KEY)
    merge_path(uri, simple(["d", "e"], p, 4), ["id"], PARTITION_KEY)
    upsert_path(uri, simple(["a", "e"], p, 5), ["id"], PARTITION_KEY)

    expected = {("a", p): 5, ("b", p): 2, ("c", p): 3, ("d", p): 4, ("e", p): 5}
    assert_valid_log(uri, expected)
    assert duckdb_content(uri) == expected


# --------------------------------------------------------------------------------------
# 2. optimize.compact() specifically
# --------------------------------------------------------------------------------------


@pytest.fixture
def fragmented(tmp_path):
    """A partition holding files from BOTH writers, small enough to be compacted."""
    uri = str(tmp_path / "frag")
    p = "2026-07-23"
    create_table(uri, simple(["a", "b"], p, 1), True)
    upsert_path(uri, simple(["b", "c"], p, 2), ["id"], PARTITION_KEY)
    deltalake.write_deltalake(uri, simple(["d"], p, 3), mode="append")
    deltalake.write_deltalake(uri, simple(["e"], p, 3), mode="append")
    expected = {("a", p): 1, ("b", p): 2, ("c", p): 2, ("d", p): 3, ("e", p): 3}
    assert content(uri) == expected
    assert len(deltalake.DeltaTable(uri).file_uris()) >= 3
    return uri, p, expected


def test_compact_after_upsert_preserves_contents_exactly(fragmented):
    uri, _, expected = fragmented
    before_rows = read_sorted(uri)

    metrics = deltalake.DeltaTable(uri).optimize.compact()
    assert metrics["numFilesRemoved"] >= 3
    assert metrics["numFilesAdded"] >= 1

    assert read_sorted(uri) == before_rows
    assert_valid_log(uri, expected)


def test_compacted_files_carry_statistics(fragmented):
    """External readers depend on Add-action stats; the files compaction writes when it
    rewrites deltalite's output must still carry them, PK column included."""
    uri, _, _ = fragmented
    deltalake.DeltaTable(uri).optimize.compact()

    log_dir = Path(uri) / "_delta_log"
    latest = sorted(log_dir.glob("*.json"))[-1]
    adds = [json.loads(line)["add"] for line in latest.read_text().splitlines() if "add" in json.loads(line)]
    assert adds, "compaction commit contained no Add actions"
    for add in adds:
        assert add.get("stats"), f"post-compact Add missing stats: {add['path']}"
        stats = json.loads(add["stats"])
        assert stats["numRecords"] > 0
        assert "id" in stats["minValues"] and "id" in stats["maxValues"]
        assert PARTITION_KEY not in stats["minValues"]


def test_upsert_after_compact(fragmented):
    """Compaction rewrote files and tombstoned the originals; the next upsert must plan
    against the compacted file set, and its stats must reflect real work."""
    uri, p, expected = fragmented
    deltalake.DeltaTable(uri).optimize.compact()

    stats = upsert_path(uri, simple(["a", "z"], p, 9), ["id"], PARTITION_KEY)
    assert stats.rows_updated == 1  # 'a' lived in the compacted file
    assert stats.files_removed >= 1

    expected.update({("a", p): 9, ("z", p): 9})
    assert_valid_log(uri, expected)


def test_compact_between_every_upsert(tmp_path):
    """Alternate upsert/compact repeatedly -- neither writer may corrupt the other."""
    uri = str(tmp_path / "alternate")
    p = "2026-07-23"
    create_table(uri, simple(["a"], p, 0), True)
    expected = {("a", p): 0}

    for i in range(1, 4):
        upsert_path(uri, simple(["a", f"k{i}"], p, i), ["id"], PARTITION_KEY)
        expected.update({("a", p): i, (f"k{i}", p): i})
        deltalake.DeltaTable(uri).optimize.compact()
        assert_valid_log(uri, expected)


# --------------------------------------------------------------------------------------
# 3. vacuum
# --------------------------------------------------------------------------------------


def test_vacuum_reclaims_deltalite_tombstones_and_keeps_live_files(tmp_path):
    uri = str(tmp_path / "vac")
    p = "2026-07-23"
    create_table(uri, simple(["a", "b"], p, 1), True)

    # this upsert tombstones the original file and writes a fresh one
    stats = upsert_path(uri, simple(["b", "c"], p, 2), ["id"], PARTITION_KEY)
    assert stats.files_removed >= 1

    on_disk = {f.name for f in Path(uri).rglob("*.parquet")}
    live = {Path(u).name for u in deltalake.DeltaTable(uri).file_uris()}
    dead = on_disk - live
    assert dead, "expected at least one tombstoned physical file before vacuum"

    deltalake.DeltaTable(uri).vacuum(retention_hours=0, enforce_retention_duration=False, dry_run=False)

    after = {f.name for f in Path(uri).rglob("*.parquet")}
    assert dead.isdisjoint(after), "vacuum failed to reclaim deltalite's tombstones"
    assert live <= after, "vacuum deleted files deltalite just wrote"

    expected = {("a", p): 1, ("b", p): 2, ("c", p): 2}
    assert_valid_log(uri, expected)


def test_upsert_immediately_after_vacuum(tmp_path):
    uri = str(tmp_path / "vac_then_upsert")
    p = "2026-07-23"
    create_table(uri, simple(["a", "b"], p, 1), True)
    upsert_path(uri, simple(["b"], p, 2), ["id"], PARTITION_KEY)
    deltalake.DeltaTable(uri).vacuum(retention_hours=0, enforce_retention_duration=False, dry_run=False)

    upsert_path(uri, simple(["a", "c"], p, 3), ["id"], PARTITION_KEY)
    assert_valid_log(uri, {("a", p): 3, ("b", p): 2, ("c", p): 3})


def test_vacuum_after_compact_after_upsert(tmp_path):
    """The production maintenance order: compact then vacuum, over deltalite commits."""
    uri = str(tmp_path / "maintenance")
    p = "2026-07-23"
    create_table(uri, simple(["a", "b"], p, 1), True)
    upsert_path(uri, simple(["b", "c"], p, 2), ["id"], PARTITION_KEY)
    deltalake.write_deltalake(uri, simple(["d"], p, 3), mode="append")

    dt = deltalake.DeltaTable(uri)
    dt.optimize.compact()
    deltalake.DeltaTable(uri).vacuum(retention_hours=0, enforce_retention_duration=False, dry_run=False)

    live = [Path(u) for u in deltalake.DeltaTable(uri).file_uris()]
    on_disk = list(Path(uri).rglob("*.parquet"))
    assert sorted(f.name for f in on_disk) == sorted(f.name for f in live), (
        "after compact+vacuum only the live file set should remain on disk"
    )
    expected = {("a", p): 1, ("b", p): 2, ("c", p): 2, ("d", p): 3}
    assert_valid_log(uri, expected)
    assert duckdb_content(uri) == expected


# --------------------------------------------------------------------------------------
# 5. history() / idempotency metadata interleaving
# --------------------------------------------------------------------------------------


def _has_commit_with_metadata(history_entries, md: dict) -> bool:
    """The production matcher: flat 1.x layout or nested userMetadata both accepted."""

    def matches(commit):
        flat = all(commit.get(k) == v for k, v in md.items())
        nested = commit.get("userMetadata")
        return flat or (isinstance(nested, dict) and all(nested.get(k) == v for k, v in md.items()))

    return any(matches(c) for c in history_entries)


def test_history_interleaved_writers_tags_all_discoverable(tmp_path):
    """Tagged commits from python append, MERGE, and deltalite must all be discoverable
    through `history()` on either handle after interleaving."""
    import deltalite

    uri = str(tmp_path / "hist")
    p = "2026-07-23"
    create_table(uri, simple(["a"], p, 1), True)

    deltalake.write_deltalake(
        uri,
        simple(["b"], p, 1),
        mode="append",
        commit_properties=deltalake.CommitProperties(custom_metadata={"run_uuid": "run-append", "batch_index": "0"}),
    )
    merge_path(
        uri,
        simple(["a"], p, 2),
        ["id"],
        PARTITION_KEY,
        {"run_uuid": "run-merge", "batch_index": "1"},
    )
    upsert_path(
        uri,
        simple(["b"], p, 3),
        ["id"],
        PARTITION_KEY,
        {"run_uuid": "run-lite", "batch_index": "2"},
    )
    merge_path(
        uri,
        simple(["c"], p, 4),
        ["id"],
        PARTITION_KEY,
        {"run_uuid": "run-merge", "batch_index": "3"},
    )
    upsert_path(
        uri,
        simple(["d"], p, 5),
        ["id"],
        PARTITION_KEY,
        {"run_uuid": "run-lite", "batch_index": "4"},
    )

    history = deltalake.DeltaTable(uri).history(20)
    for md in [
        {"run_uuid": "run-append", "batch_index": "0"},
        {"run_uuid": "run-merge", "batch_index": "1"},
        {"run_uuid": "run-lite", "batch_index": "2"},
        {"run_uuid": "run-merge", "batch_index": "3"},
        {"run_uuid": "run-lite", "batch_index": "4"},
    ]:
        assert _has_commit_with_metadata(history, md), f"tag not found: {md}"
    # a batch that never ran must NOT be found
    assert not _has_commit_with_metadata(history, {"run_uuid": "run-lite", "batch_index": "99"})

    # deltalite's own history() sees the python-written tags too
    lite_hist = deltalite.DeltaLiteTable.open(uri).history(20)
    infos = [h["info"] for h in lite_hist]
    assert any('"run-append"' in str(i.get("run_uuid")) for i in infos)
    assert any('"run-merge"' in str(i.get("run_uuid")) for i in infos)


def test_history_survives_compact_and_vacuum(tmp_path):
    """Maintenance commits interleave with tagged writes; earlier tags must remain
    discoverable within the helper's lookback window."""
    uri = str(tmp_path / "hist_maint")
    p = "2026-07-23"
    create_table(uri, simple(["a", "b"], p, 1), True)
    upsert_path(
        uri,
        simple(["b"], p, 2),
        ["id"],
        PARTITION_KEY,
        {"run_uuid": "run-x", "batch_index": "0"},
    )
    # a second file so compact does real work and actually commits
    deltalake.write_deltalake(uri, simple(["x"], p, 9), mode="append")
    deltalake.DeltaTable(uri).optimize.compact()
    deltalake.DeltaTable(uri).vacuum(retention_hours=0, enforce_retention_duration=False, dry_run=False)
    upsert_path(
        uri,
        simple(["c"], p, 3),
        ["id"],
        PARTITION_KEY,
        {"run_uuid": "run-x", "batch_index": "1"},
    )

    history = deltalake.DeltaTable(uri).history(20)
    assert _has_commit_with_metadata(history, {"run_uuid": "run-x", "batch_index": "0"})
    assert _has_commit_with_metadata(history, {"run_uuid": "run-x", "batch_index": "1"})
    ops = [c.get("operation") for c in history]
    assert "OPTIMIZE" in ops and "VACUUM END" in ops


# --------------------------------------------------------------------------------------
# 6. Partition downgrade + unsupported-table refusal
# --------------------------------------------------------------------------------------


def test_unpartitioned_table_downgraded_even_with_partition_hint(tmp_path):
    """The table's own metadata, not the caller's hint, decides partitioning: an
    unpartitioned table upserted WITH partition_key must behave exactly like the
    unpartitioned MERGE (identity = PKs only, whole-table handling)."""
    uri_m = str(tmp_path / "down_m")
    uri_u = str(tmp_path / "down_u")
    p1, p2 = "2026-07-23", "2026-07-24"
    initial = simple(["a", "b"], p1, 1)
    create_table(uri_m, initial, False)  # NOT partitioned
    create_table(uri_u, initial, False)

    # same PK arriving under a DIFFERENT partition value: unpartitioned identity is PK
    # only, so this must UPDATE 'a' (a partitioned table would insert a second row)
    batch = simple(["a", "c"], p2, 2)
    merge_path(uri_m, batch, ["id"], None)  # production downgrades to no partition key
    stats = upsert_path(uri_u, batch, ["id"], PARTITION_KEY)  # hint passed anyway

    assert stats.partitions_touched == 1  # one whole-table group, not per-value groups
    assert read_sorted(uri_m) == read_sorted(uri_u)
    assert content(uri_u) == {("a", p2): 2, ("b", p1): 1, ("c", p2): 2}


def test_table_partitioned_by_other_column_with_hint_is_refused(tmp_path):
    """A table partitioned by something other than the hinted key must be refused
    cleanly, not silently treated as either partitioning."""
    import deltalite

    uri = str(tmp_path / "otherpart")
    tb = pa.table(
        {
            "id": pa.array(["a", "b"], pa.string()),
            "v": pa.array([1, 1], pa.int64()),
            "region": pa.array(["eu", "us"], pa.string()),
        }
    )
    deltalake.write_deltalake(uri, tb, partition_by=["region"], mode="overwrite")

    t = deltalite.DeltaLiteTable.open(uri)
    with pytest.raises(deltalite.DeltaLiteError, match="partitioned by 'region'"):
        t.upsert(
            pa.table(
                {
                    "id": pa.array(["a"], pa.string()),
                    "v": pa.array([2], pa.int64()),
                    "region": pa.array(["eu"], pa.string()),
                }
            ),
            ["id"],
            PARTITION_KEY,
        )
    # and the failed call must not have committed anything
    assert deltalake.DeltaTable(uri).version() == 0


def test_deletion_vector_table_is_refused_cleanly(tmp_path):
    """A table created (via the python package) with deletion vectors enabled must be
    refused with the typed error, before any commit."""
    import deltalite

    uri = str(tmp_path / "dv")
    schema = simple([], "p", [])[:0].schema
    deltalake.DeltaTable.create(
        uri,
        deltalake.Schema.from_arrow(schema),
        partition_by=[PARTITION_KEY],
        configuration={"delta.enableDeletionVectors": "true"},
    )
    proto = deltalake.DeltaTable(uri).protocol()
    assert "deletionVectors" in (proto.writer_features or [])

    t = deltalite.DeltaLiteTable.open(uri)
    with pytest.raises(deltalite.DeltaLiteUnsupportedTableError, match="deletionVectors"):
        t.upsert(simple(["a"], "p", 1), ["id"], PARTITION_KEY)
    assert deltalake.DeltaTable(uri).version() == 0


def test_legacy_column_mapping_table_is_refused(tmp_path):
    """A LEGACY-protocol column-mapping table (minReaderVersion=2/minWriterVersion=5,
    no feature lists) -- the python package cannot create one, but they exist in the
    wild, so the log is crafted by hand.

    FINDING: `ensure_supported_table` (src/upsert.rs) does NOT catch this shape -- its
    feature-list check only fires for protocol v3/v7 feature tables, and its
    configuration check only looks at delta.enableDeletionVectors, not
    delta.columnMapping.mode. The refusal below actually comes from
    `RecordBatchWriter::for_table` ("column mapping writes are not supported"), so it
    is safe today but surfaces as a generic DeltaLiteError instead of
    DeltaLiteUnsupportedTableError. This test pins that the table is refused at all;
    if it ever starts succeeding, that is silent corruption.
    """
    import deltalite

    uri = str(tmp_path / "cm_legacy")
    log = Path(uri) / "_delta_log"
    log.mkdir(parents=True)
    schema_str = json.dumps(
        {
            "type": "struct",
            "fields": [
                {
                    "name": "id",
                    "type": "string",
                    "nullable": True,
                    "metadata": {
                        "delta.columnMapping.id": 1,
                        "delta.columnMapping.physicalName": "col-1",
                    },
                },
                {
                    "name": "v",
                    "type": "long",
                    "nullable": True,
                    "metadata": {
                        "delta.columnMapping.id": 2,
                        "delta.columnMapping.physicalName": "col-2",
                    },
                },
            ],
        }
    )
    with open(log / "00000000000000000000.json", "w") as f:
        f.write(json.dumps({"protocol": {"minReaderVersion": 2, "minWriterVersion": 5}}) + "\n")
        f.write(
            json.dumps(
                {
                    "metaData": {
                        "id": "11111111-1111-1111-1111-111111111111",
                        "format": {"provider": "parquet", "options": {}},
                        "schemaString": schema_str,
                        "partitionColumns": [],
                        "configuration": {
                            "delta.columnMapping.mode": "name",
                            "delta.columnMapping.maxColumnId": "2",
                        },
                        "createdTime": 1700000000000,
                    }
                }
            )
            + "\n"
        )

    # the python package opens it fine
    assert deltalake.DeltaTable(uri).metadata().configuration["delta.columnMapping.mode"] == "name"

    t = deltalite.DeltaLiteTable.open(uri)
    with pytest.raises(deltalite.DeltaLiteError):
        t.upsert(
            pa.table({"id": pa.array(["a"]), "v": pa.array([1], pa.int64())}),
            ["id"],
            None,
        )
    assert deltalake.DeltaTable(uri).version() == 0


def test_is_deltatable_agrees_after_mixed_writers(tmp_path):
    import deltalite

    uri = str(tmp_path / "exists")
    assert deltalake.DeltaTable.is_deltatable(uri) is False
    assert deltalite.DeltaLiteTable.is_deltatable(uri) is False

    p = "2026-07-23"
    create_table(uri, simple(["a"], p, 1), True)
    upsert_path(uri, simple(["b"], p, 2), ["id"], PARTITION_KEY)

    assert deltalake.DeltaTable.is_deltatable(uri) is True
    assert deltalite.DeltaLiteTable.is_deltatable(uri) is True
    assert sorted(deltalake.DeltaTable(uri).file_uris()) == sorted(deltalite.DeltaLiteTable.open(uri).file_uris())


# --------------------------------------------------------------------------------------
# `delta.targetFileSize` must be honoured, as it is by every other delta-rs operation
# --------------------------------------------------------------------------------------


def _tfs_table(uri, rows, target_file_size=None, payload=2000, update_rows=None):
    """Build a table, and return a batch that updates only part of it.

    The updated fraction matters: rows that are REPLACED never reach the writer, so a
    batch matching everything produces no survivors and the periodic flush never runs.
    """
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
    from bench import gen

    batch = gen.make_batch(0, rows, "2026-07-23", payload)
    cfg = {"delta.targetFileSize": str(target_file_size)} if target_file_size else None
    deltalake.write_deltalake(uri, batch, partition_by=[PARTITION_KEY], mode="overwrite", configuration=cfg)
    return gen.make_batch(0, update_rows or (rows // 10), "2026-07-23", payload, version=2)


def _added_file_sizes(uri, version):
    log = Path(uri) / "_delta_log" / f"{version:020d}.json"
    return [json.loads(line)["add"]["size"] for line in log.read_text().splitlines() if "add" in json.loads(line)]


def test_upsert_honours_delta_target_file_size(tmp_path):
    """A table configured with a small target must get small files from upsert too.

    Every other delta-rs operation reads `delta.targetFileSize`; upsert hardcoding its
    own default would make it the odd one out on a table that sets the property.
    """
    import deltalite

    uri = str(tmp_path / "tfs_small")
    batch = _tfs_table(uri, 40_000, target_file_size=4 * 1024 * 1024)  # 4 MiB
    stats = deltalite.DeltaLiteTable.open(uri).upsert(batch, ["id"], PARTITION_KEY, prune_strategy="none")

    sizes = _added_file_sizes(uri, stats.version)
    assert stats.files_added > 1, f"a 4 MiB target should split the survivors into several files, got {stats}"
    assert max(sizes) < 32 * 1024 * 1024, f"file far larger than the 4 MiB target: {sizes}"


def test_upsert_uses_the_delta_rs_default_when_unset(tmp_path):
    """No property set -> one ~85 MB partition fits in delta-rs's 100 MiB default."""
    import deltalite

    uri = str(tmp_path / "tfs_default")
    batch = _tfs_table(uri, 40_000)
    stats = deltalite.DeltaLiteTable.open(uri).upsert(batch, ["id"], PARTITION_KEY, prune_strategy="none")
    assert stats.files_added == 1, "should not split below the 100 MiB default"


def test_explicit_argument_overrides_the_table_property(tmp_path):
    import deltalite

    uri = str(tmp_path / "tfs_override")
    batch = _tfs_table(uri, 40_000, target_file_size=4 * 1024 * 1024)
    stats = deltalite.DeltaLiteTable.open(uri).upsert(
        batch,
        ["id"],
        PARTITION_KEY,
        target_file_size=100 * 1024 * 1024,
        prune_strategy="none",
    )
    assert stats.files_added == 1, "explicit argument must win over the table property"


def test_large_source_is_also_split_by_the_target(tmp_path):
    """The source write must respect the threshold too, not just the survivor stream.

    The periodic flush lives in the loop that consumes *survivors*, so a batch that
    matches every target row never passes through it. Without a check on the source
    path, such a batch produced one oversized file and an unbounded write buffer.
    """
    import deltalite

    uri = str(tmp_path / "tfs_source")
    # Every row matches, so there are zero survivors and only the source is written.
    batch = _tfs_table(uri, 40_000, target_file_size=4 * 1024 * 1024, update_rows=40_000)
    stats = deltalite.DeltaLiteTable.open(uri).upsert(batch, ["id"], PARTITION_KEY, prune_strategy="none")

    assert stats.rows_copied == 0, "test intends a full-match batch (no survivors)"
    sizes = _added_file_sizes(uri, stats.version)
    assert stats.files_added > 1, f"source write ignored the 4 MiB target: {stats}"
    assert max(sizes) < 32 * 1024 * 1024, f"file far larger than the target: {sizes}"
