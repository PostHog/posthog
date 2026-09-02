"""Differential parity: delta-rs SQL MERGE vs deltalite streaming partition upsert.

Every scenario applies the *same* batch sequence to two fresh tables, one through each
path, and asserts the resulting logical content is identical. A single mismatch here is a
NO-GO signal.
"""

from __future__ import annotations

import io
import sys
import decimal
from pathlib import Path

import pytest

import pyarrow as pa
import deltalake
import pyarrow.ipc as ipc

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.common import (  # noqa: E402
    PARTITION_KEY,
    Scenario,
    assert_parity,
    create_table,
    dedupe_keep_last,
    gen_wide,
    merge_path,
    read_sorted,
    run_scenario,
    upsert_path,
    uuid_ids,
)

# --------------------------------------------------------------------------------------
# Small helpers for building scenario data
# --------------------------------------------------------------------------------------


def simple(ids, part, v, tenant=None):
    """id (string PK) + v (int) + partition key."""
    n = len(ids)
    return pa.table(
        {
            "id": pa.array(ids, pa.string()),
            "tenant": pa.array(tenant if tenant is not None else [1] * n, pa.int64()),
            "v": pa.array([v] * n if isinstance(v, int) else v, pa.int64()),
            PARTITION_KEY: pa.array(part if isinstance(part, list) else [part] * n, pa.string()),
        }
    )


# --------------------------------------------------------------------------------------
# Scenarios
# --------------------------------------------------------------------------------------


def sc_partitioned_basic():
    return Scenario(
        name="partitioned_basic",
        initial=simple(["a", "b", "c", "d"], "2026-07-23", 1),
        batches=[
            simple(["b", "c", "e"], "2026-07-23", 2),  # 2 updates, 1 insert
            simple(["a", "f"], "2026-07-23", 3),
        ],
        primary_keys=["id"],
    )


def sc_unpartitioned_basic():
    return Scenario(
        name="unpartitioned_basic",
        initial=simple(["a", "b", "c", "d"], "2026-07-23", 1),
        batches=[
            simple(["b", "c", "e"], "2026-07-23", 2),
            simple(["a", "f"], "2026-07-23", 3),
        ],
        primary_keys=["id"],
        partitioned=False,
    )


def sc_composite_pk():
    return Scenario(
        name="composite_pk",
        initial=simple(["a", "a", "b"], "2026-07-23", 1, tenant=[1, 2, 1]),
        batches=[
            # (a,2) updates; (a,3) inserts; (b,1) updates
            simple(["a", "a", "b"], "2026-07-23", 5, tenant=[2, 3, 1]),
        ],
        primary_keys=["id", "tenant"],
    )


def sc_composite_pk_unpartitioned():
    s = sc_composite_pk()
    s.name = "composite_pk_unpartitioned"
    s.partitioned = False
    return s


def sc_null_pk_single():
    """NULL PKs must always insert and never match -- SQL NULL != NULL."""
    return Scenario(
        name="null_pk_single",
        initial=simple(["a", None, "c"], "2026-07-23", 1),
        batches=[
            simple([None, "a"], "2026-07-23", 2),  # NULL must insert, not update
            simple([None], "2026-07-23", 3),  # another distinct NULL row
        ],
        primary_keys=["id"],
    )


def sc_null_pk_composite():
    """NULL in *any* PK component makes the whole tuple unmatchable."""
    return Scenario(
        name="null_pk_composite",
        initial=pa.table(
            {
                "id": pa.array(["a", "b", None], pa.string()),
                "tenant": pa.array([1, None, 3], pa.int64()),
                "v": pa.array([1, 1, 1], pa.int64()),
                PARTITION_KEY: pa.array(["2026-07-23"] * 3, pa.string()),
            }
        ),
        batches=[
            pa.table(
                {
                    "id": pa.array(["a", "b", None], pa.string()),
                    "tenant": pa.array([1, None, 3], pa.int64()),
                    "v": pa.array([9, 9, 9], pa.int64()),
                    PARTITION_KEY: pa.array(["2026-07-23"] * 3, pa.string()),
                }
            )
        ],
        primary_keys=["id", "tenant"],
    )


def sc_null_pk_unpartitioned():
    s = sc_null_pk_single()
    s.name = "null_pk_unpartitioned"
    s.partitioned = False
    return s


def sc_intra_batch_duplicates():
    return Scenario(
        name="intra_batch_duplicates",
        initial=simple(["a", "b"], "2026-07-23", 1),
        batches=[
            # 'a' appears three times: keep-last must win (v=30)
            simple(["a", "a", "a", "c"], "2026-07-23", [10, 20, 30, 40]),
        ],
        primary_keys=["id"],
    )


def sc_pk_changes_partition():
    """A PK that moves partition: the old row is deliberately left behind."""
    return Scenario(
        name="pk_changes_partition",
        initial=simple(["a", "b"], "2026-07-23", 1),
        batches=[simple(["a"], "2026-07-24", 2)],
        primary_keys=["id"],
    )


def sc_new_partition():
    return Scenario(
        name="new_partition",
        initial=simple(["a", "b"], "2026-07-23", 1),
        batches=[
            simple(["x", "y"], "2026-07-25", 2),
            simple(["a", "z"], ["2026-07-23", "2026-07-26"], 3),
        ],
        primary_keys=["id"],
    )


def sc_empty_batch():
    return Scenario(
        name="empty_batch",
        initial=simple(["a", "b"], "2026-07-23", 1),
        batches=[
            simple([], "2026-07-23", []),
            simple(["a"], "2026-07-23", 5),
        ],
        primary_keys=["id"],
    )


# Partition values that are hostile but that MERGE can still express. The
# single-quote case cannot be expressed by the current code at all and is covered
# separately in `test_single_quote_partition_value_*` below.
HOSTILE_QUOTE_FREE = ["2026-07-23", 'quote"dq', "üñîçødé", "sp ace", "back\\slash", "a,b"]
HOSTILE_WITH_QUOTE = "o'brien"


def sc_hostile_partition_values():
    """Unicode / quote-adjacent partition values that MERGE can still express."""
    vals = HOSTILE_QUOTE_FREE
    return Scenario(
        name="hostile_partition_values",
        initial=simple([f"i{i}" for i in range(len(vals))], vals, 1),
        batches=[simple([f"i{i}" for i in range(len(vals))], vals, 2)],
        primary_keys=["id"],
    )


def sc_all_rows_replaced():
    return Scenario(
        name="all_rows_replaced",
        initial=simple(["a", "b", "c"], "2026-07-23", 1),
        batches=[simple(["a", "b", "c"], "2026-07-23", 2)],
        primary_keys=["id"],
    )


def sc_many_partitions():
    parts = [f"2026-07-{d:02d}" for d in range(1, 13)]
    ids = [f"k{i}" for i in range(len(parts))]
    return Scenario(
        name="many_partitions",
        initial=simple(ids, parts, 1),
        batches=[simple(ids, parts, 2), simple(ids[:5], parts[:5], 3)],
        primary_keys=["id"],
    )


def sc_decimal_wide():
    ids = uuid_ids(40)
    return Scenario(
        name="decimal_wide",
        initial=gen_wide(ids, "2026-07-23", seed=1, payload_size=600, version=1),
        batches=[
            gen_wide(ids[10:30], "2026-07-23", seed=2, payload_size=600, version=2),
            gen_wide(uuid_ids(10, offset=100), "2026-07-24", seed=3, payload_size=600, version=3),
        ],
        primary_keys=["id"],
    )


SCENARIOS = [
    sc_partitioned_basic,
    sc_unpartitioned_basic,
    sc_composite_pk,
    sc_composite_pk_unpartitioned,
    sc_null_pk_single,
    sc_null_pk_composite,
    sc_null_pk_unpartitioned,
    sc_intra_batch_duplicates,
    sc_pk_changes_partition,
    sc_new_partition,
    sc_empty_batch,
    sc_hostile_partition_values,
    sc_all_rows_replaced,
    sc_many_partitions,
    sc_decimal_wide,
]


@pytest.mark.parametrize("builder", SCENARIOS, ids=[f.__name__[3:] for f in SCENARIOS])
def test_parity(builder, tmp_path):
    scenario = builder()
    uri_m, uri_u = run_scenario(scenario, tmp_path)
    assert_parity(uri_m, uri_u, scenario.name)


# --------------------------------------------------------------------------------------
# Cases that need bespoke driving rather than the generic scenario runner
# --------------------------------------------------------------------------------------


def test_schema_evolution_midsequence(tmp_path):
    """An additive column appears mid-sequence; old files must read up as NULL."""
    uri_m = str(tmp_path / "evo_merge")
    uri_u = str(tmp_path / "evo_upsert")
    initial = simple(["a", "b", "c"], "2026-07-23", 1)
    create_table(uri_m, initial, True)
    create_table(uri_u, initial, True)

    b1 = simple(["b"], "2026-07-23", 2)
    evolved = pa.table(
        {
            "id": pa.array(["c", "d"], pa.string()),
            "tenant": pa.array([1, 1], pa.int64()),
            "v": pa.array([7, 8], pa.int64()),
            "new_col": pa.array(["x", "y"], pa.string()),
            PARTITION_KEY: pa.array(["2026-07-23"] * 2, pa.string()),
        }
    )

    for uri, path in ((uri_m, merge_path), (uri_u, upsert_path)):
        path(uri, b1, ["id"], PARTITION_KEY, {"run_uuid": "r", "batch_index": "0"})
        path(uri, evolved, ["id"], PARTITION_KEY, {"run_uuid": "r", "batch_index": "1"})

    assert_parity(uri_m, uri_u, "schema_evolution")
    rows, _ = read_sorted(uri_u)
    assert len(rows) == 4


def test_decimal_misaligned_buffer(tmp_path):
    """delta-rs#3884: a Decimal128 buffer that is 8- but not 16-byte aligned.

    An Arrow IPC round-trip reliably produces one. The crate must realign on ingest
    rather than aborting.
    """
    uri_m = str(tmp_path / "dec_merge")
    uri_u = str(tmp_path / "dec_upsert")

    def mk(ids, vals):
        return pa.table(
            {
                "id": pa.array(ids, pa.string()),
                "amount": pa.array([decimal.Decimal(v) for v in vals], pa.decimal128(38, 10)),
                PARTITION_KEY: pa.array(["2026-07-23"] * len(ids), pa.string()),
            }
        )

    initial = mk(["a", "b", "c"], ["1.5", "2.5", "3.5"])
    create_table(uri_m, initial, True)
    create_table(uri_u, initial, True)

    src = mk(["b", "d"], ["99.5", "7.25"])
    sink = io.BytesIO()
    w = ipc.new_stream(sink, src.schema)
    w.write_table(src)
    w.close()
    misaligned = ipc.open_stream(io.BytesIO(sink.getvalue())).read_all()

    addr = misaligned.column("amount").chunk(0).buffers()[1].address
    assert addr % 16 == 8, "expected an 8-but-not-16 byte aligned decimal buffer"

    merge_path(uri_m, misaligned, ["id"], PARTITION_KEY, None)
    upsert_path(uri_u, misaligned, ["id"], PARTITION_KEY, None)
    assert_parity(uri_m, uri_u, "decimal_misaligned")


def test_batch_spans_multiple_row_groups(tmp_path):
    """Existing files with several row groups must stream correctly."""
    uri_m = str(tmp_path / "rg_merge")
    uri_u = str(tmp_path / "rg_upsert")

    n = 20_000
    ids = uuid_ids(n)
    initial = simple(ids, "2026-07-23", 1)
    props = deltalake.WriterProperties(max_row_group_size=1000)  # ~20 row groups
    for uri in (uri_m, uri_u):
        deltalake.write_deltalake(
            uri,
            initial,
            partition_by=[PARTITION_KEY],
            mode="overwrite",
            writer_properties=props,
        )

    # Update half the rows, insert 5k new ones.
    batch = simple(ids[::2] + uuid_ids(5000, offset=n), "2026-07-23", 2)
    merge_path(uri_m, batch, ["id"], PARTITION_KEY, None)
    stats = upsert_path(uri_u, batch, ["id"], PARTITION_KEY, None)

    assert_parity(uri_m, uri_u, "multi_row_group")
    rows, _ = read_sorted(uri_u)
    assert len(rows) == n + 5000
    assert stats.rows_updated == n // 2


def test_idempotency_tag_is_discoverable(tmp_path):
    """`has_commit_with_metadata` must find deltalite's tag exactly as it finds merge's."""
    uri = str(tmp_path / "idem")
    create_table(uri, simple(["a", "b"], "2026-07-23", 1), True)
    upsert_path(
        uri,
        simple(["a", "c"], "2026-07-23", 2),
        ["id"],
        PARTITION_KEY,
        {"run_uuid": "run-xyz", "batch_index": "7"},
    )

    history = deltalake.DeltaTable(uri).history(5)

    def matches(commit, md):
        flat = all(commit.get(k) == v for k, v in md.items())
        nested = commit.get("userMetadata")
        return flat or (isinstance(nested, dict) and all(nested.get(k) == v for k, v in md.items()))

    assert any(matches(c, {"run_uuid": "run-xyz", "batch_index": "7"}) for c in history), (
        f"idempotency tag not discoverable in history: {history}"
    )


def test_empty_batch_still_tags_the_commit(tmp_path):
    """Open question from the design: does an action-less commit land?"""
    uri = str(tmp_path / "empty_tag")
    create_table(uri, simple(["a", "b"], "2026-07-23", 1), True)
    before = deltalake.DeltaTable(uri).version()

    stats = upsert_path(
        uri,
        simple([], "2026-07-23", []),
        ["id"],
        PARTITION_KEY,
        {"run_uuid": "run-empty", "batch_index": "0"},
    )

    after = deltalake.DeltaTable(uri).version()
    assert after == before + 1, "empty batch did not produce a commit"
    assert stats.files_added == 0 and stats.files_removed == 0
    history = deltalake.DeltaTable(uri).history(3)
    assert any(c.get("run_uuid") == "run-empty" for c in history)


def test_duplicate_pks_in_source_are_rejected(tmp_path):
    """The crate must refuse an un-deduped batch rather than double-insert."""
    import deltalite

    uri = str(tmp_path / "dupe")
    create_table(uri, simple(["a"], "2026-07-23", 1), True)
    raw = simple(["b", "b"], "2026-07-23", [1, 2])  # deliberately NOT deduped

    t = deltalite.DeltaLiteTable.open(uri)
    with pytest.raises(deltalite.DeltaLiteError, match="duplicate primary-key"):
        t.upsert(raw, ["id"], PARTITION_KEY)


def test_dedupe_helper_keeps_last(tmp_path):
    batch = simple(["a", "a", "b"], "2026-07-23", [1, 2, 3])
    out = dedupe_keep_last(batch, ["id"], PARTITION_KEY)
    d = dict(zip(out["id"].to_pylist(), out["v"].to_pylist()))
    assert d == {"a": 2, "b": 3}


# --------------------------------------------------------------------------------------
# The single-quote partition value: a pre-existing MERGE defect, not a deltalite one
# --------------------------------------------------------------------------------------


def _quote_scenario_tables(tmp_path, name):
    uri = str(tmp_path / name)
    initial = simple(["i0", "i1"], [HOSTILE_WITH_QUOTE, "2026-07-23"], 1)
    create_table(uri, initial, True)
    return uri, simple(["i0", "i1"], [HOSTILE_WITH_QUOTE, "2026-07-23"], 2)


def test_single_quote_partition_value_breaks_merge(tmp_path):
    """Documents the current production sharp edge.

    `DeltaTableHelper` interpolates the partition value straight into a SQL predicate
    (`target._ph_partition_key = '{partition}'`), so a value containing a single quote
    produces invalid SQL. This is a live bug on the existing code path.
    """
    uri, batch = _quote_scenario_tables(tmp_path, "quote_merge")
    with pytest.raises(Exception) as exc:
        merge_path(uri, batch, ["id"], PARTITION_KEY, None)
    assert "Unterminated string literal" in str(exc.value) or "SQL" in str(exc.value)


def test_single_quote_partition_value_works_in_deltalite(tmp_path):
    """deltalite never builds a SQL predicate, so the same value is handled."""
    uri, batch = _quote_scenario_tables(tmp_path, "quote_upsert")
    upsert_path(uri, batch, ["id"], PARTITION_KEY, None)

    rows, _ = read_sorted(uri)
    assert len(rows) == 2
    tbl = deltalake.DeltaTable(uri).to_pyarrow_table().sort_by("id")
    assert tbl["v"].to_pylist() == [2, 2]
    assert set(tbl[PARTITION_KEY].to_pylist()) == {HOSTILE_WITH_QUOTE, "2026-07-23"}


# --------------------------------------------------------------------------------------
# Absolute expectations. Cross-path equality cannot catch both paths being wrong in the
# same way, so the semantically load-bearing cases are also pinned to explicit content.
# --------------------------------------------------------------------------------------


def _content(uri):
    tbl = deltalake.DeltaTable(uri).to_pyarrow_table()
    return sorted(
        zip(tbl["id"].to_pylist(), tbl["v"].to_pylist(), tbl[PARTITION_KEY].to_pylist()),
        key=lambda r: (r[0] is None, str(r[0]), r[1]),
    )


@pytest.mark.parametrize("path_name", ["merge", "upsert"])
def test_null_pk_absolute_semantics(tmp_path, path_name):
    """A NULL PK must never match: every NULL-keyed source row inserts a new row."""
    path = merge_path if path_name == "merge" else upsert_path
    uri = str(tmp_path / f"nullabs_{path_name}")
    create_table(uri, simple(["a", None, "c"], "2026-07-23", 1), True)

    path(uri, simple([None, "a"], "2026-07-23", 2), ["id"], PARTITION_KEY, None)
    path(uri, simple([None], "2026-07-23", 3), ["id"], PARTITION_KEY, None)

    assert _content(uri) == [
        ("a", 2, "2026-07-23"),  # matched and updated
        ("c", 1, "2026-07-23"),  # untouched
        (None, 1, "2026-07-23"),  # original NULL row survives
        (None, 2, "2026-07-23"),  # first NULL insert
        (None, 3, "2026-07-23"),  # second NULL insert
    ]


@pytest.mark.parametrize("path_name", ["merge", "upsert"])
def test_pk_changing_partition_absolute_semantics(tmp_path, path_name):
    """Identity is (PK, partition): a moved PK inserts and leaves the old row behind."""
    path = merge_path if path_name == "merge" else upsert_path
    uri = str(tmp_path / f"moveabs_{path_name}")
    create_table(uri, simple(["a", "b"], "2026-07-23", 1), True)

    path(uri, simple(["a"], "2026-07-24", 2), ["id"], PARTITION_KEY, None)

    assert _content(uri) == [
        ("a", 1, "2026-07-23"),  # stale row deliberately NOT deleted
        ("a", 2, "2026-07-24"),  # new partition gets the new row
        ("b", 1, "2026-07-23"),
    ]


@pytest.mark.parametrize("path_name", ["merge", "upsert"])
def test_composite_pk_absolute_semantics(tmp_path, path_name):
    path = merge_path if path_name == "merge" else upsert_path
    uri = str(tmp_path / f"compabs_{path_name}")
    create_table(uri, simple(["a", "a", "b"], "2026-07-23", 1, tenant=[1, 2, 1]), True)

    path(
        uri,
        simple(["a", "a"], "2026-07-23", 5, tenant=[2, 3]),
        ["id", "tenant"],
        PARTITION_KEY,
        None,
    )

    tbl = deltalake.DeltaTable(uri).to_pyarrow_table()
    got = sorted(zip(tbl["id"].to_pylist(), tbl["tenant"].to_pylist(), tbl["v"].to_pylist()))
    assert got == [
        ("a", 1, 1),  # untouched: only (a,2) matched
        ("a", 2, 5),  # updated
        ("a", 3, 5),  # inserted
        ("b", 1, 1),
    ]
