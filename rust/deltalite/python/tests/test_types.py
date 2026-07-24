"""Type-surface parity: deltalite vs delta-rs SQL MERGE across the arrow types a
warehouse sync actually produces.

Two axes:
  * value columns -- every type must survive the streaming rewrite (write, read back,
    cast, filter, re-write) with content identical to MERGE's;
  * primary-key columns -- every type that could legitimately be a PK must produce the
    same match/insert decisions in deltalite's RowConverter-encoded hash set
    (src/pkset.rs) as in MERGE's join, including the float -0.0/NaN sharp edges.

Any case where the two paths disagree, or where deltalite errors and MERGE succeeds,
is a NO-GO finding, not a skip.
"""

from __future__ import annotations

import sys
import decimal
import datetime
from pathlib import Path

import pytest

import pyarrow as pa
import deltalake

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.common import PARTITION_KEY, create_table, merge_path, read_sorted, upsert_path  # noqa: E402

TS = datetime.datetime(2026, 1, 1)
UTC = datetime.UTC
D = decimal.Decimal


def _dual(tmp_path, name, initial):
    uri_m = str(tmp_path / f"{name}_m")
    uri_u = str(tmp_path / f"{name}_u")
    create_table(uri_m, initial, True)
    create_table(uri_u, initial, True)
    return uri_m, uri_u


def _assert_type_parity(uri_m, uri_u, batches, primary_keys, label):
    """Drive both paths with the same batches, then compare logical content."""
    for batch in batches:
        merge_path(uri_m, batch, primary_keys, PARTITION_KEY)
        upsert_path(uri_u, batch, primary_keys, PARTITION_KEY)
    rows_m, schema_m = read_sorted(uri_m)
    rows_u, schema_u = read_sorted(uri_u)
    assert schema_m == schema_u, f"[{label}] schema: {schema_m} != {schema_u}"
    # Compare via str(): NaN != NaN under tuple equality, but str() is stable and also
    # distinguishes -0.0 from 0.0.
    norm_m = [tuple(str(v) for v in r) for r in rows_m]
    norm_u = [tuple(str(v) for v in r) for r in rows_u]
    assert norm_m == norm_u, f"[{label}] content mismatch:\n  merge : {rows_m}\n  upsert: {rows_u}"


# --------------------------------------------------------------------------------------
# Value columns: string PK, the type under test as a payload column.
# Three batches so the second/third upserts must stream back and cast the nested
# Parquet files the first upsert wrote.
# --------------------------------------------------------------------------------------


def _val_table(ids, col):
    return pa.table(
        {
            "id": pa.array(ids, pa.string()),
            "x": col,
            PARTITION_KEY: pa.array(["2026-07-23"] * len(ids), pa.string()),
        }
    )


STRUCT_T = pa.struct([("a", pa.int64()), ("b", pa.string())])
DEEP_T = pa.struct(
    [
        ("inner", pa.struct([("n", pa.int64()), ("s", pa.string())])),
        ("tags", pa.list_(pa.string())),
    ]
)

VALUE_CASES = {
    "bool": (
        pa.array([True, False, None], pa.bool_()),
        pa.array([False, None], pa.bool_()),
        pa.array([True, True], pa.bool_()),
    ),
    "float32": (
        pa.array([1.5, -2.5, None], pa.float32()),
        pa.array([9.5, None], pa.float32()),
        pa.array([0.0, -0.0], pa.float32()),
    ),
    "float64": (
        pa.array([1.5, float("nan"), None], pa.float64()),
        pa.array([float("inf"), None], pa.float64()),
        pa.array([float("nan"), -0.0], pa.float64()),
    ),
    "binary": (
        pa.array([b"\x00\x01", b"", None], pa.binary()),
        pa.array([b"\xff" * 8, None], pa.binary()),
        pa.array([b"q", b"\x00"], pa.binary()),
    ),
    "fixed_size_binary": (
        pa.array([b"aaaa", b"bbbb", None], pa.binary(4)),
        pa.array([b"cccc", None], pa.binary(4)),
        pa.array([b"dddd", b"\x00\x00\x00\x00"], pa.binary(4)),
    ),
    "large_binary": (
        pa.array([b"a", b"b", None], pa.large_binary()),
        pa.array([b"c", None], pa.large_binary()),
        pa.array([b"d", b"e"], pa.large_binary()),
    ),
    "date32": (
        pa.array([datetime.date(2026, 1, 1), datetime.date(1970, 1, 1), None], pa.date32()),
        pa.array([datetime.date(2026, 2, 2), None], pa.date32()),
        pa.array([datetime.date(1900, 1, 1), datetime.date(2100, 12, 31)], pa.date32()),
    ),
    "timestamp_tz": (
        pa.array([TS.replace(tzinfo=UTC)] * 2 + [None], pa.timestamp("us", tz="UTC")),
        pa.array([TS.replace(tzinfo=UTC) + datetime.timedelta(days=1), None], pa.timestamp("us", tz="UTC")),
        pa.array([TS.replace(tzinfo=UTC)] * 2, pa.timestamp("us", tz="UTC")),
    ),
    "timestamp_tz_offset": (
        pa.array([1, 2, None], pa.timestamp("s", tz="+02:00")),
        pa.array([3, None], pa.timestamp("s", tz="+02:00")),
        pa.array([4, 5], pa.timestamp("s", tz="+02:00")),
    ),
    "timestamp_ns": (
        pa.array([1, 2, None], pa.timestamp("ns")),
        pa.array([3, None], pa.timestamp("ns")),
        pa.array([4, 5], pa.timestamp("ns")),
    ),
    "large_string": (
        pa.array(["x" * 100, "", None], pa.large_string()),
        pa.array(["y", None], pa.large_string()),
        pa.array(["z", "w"], pa.large_string()),
    ),
    "dictionary": (
        pa.array(["red", "blue", "red"]).dictionary_encode(),
        pa.array(["green", "red"]).dictionary_encode(),
        pa.array(["blue", "blue"]).dictionary_encode(),
    ),
    # NOTE: delta stores uint32 as signed int32, so values must fit in i32; a uint32
    # value >= 2**31 fails at CREATE time for both writers equally (not a deltalite gap).
    "uint32": (
        pa.array([1, 2**31 - 1, None], pa.uint32()),
        pa.array([7, None], pa.uint32()),
        pa.array([0, 3], pa.uint32()),
    ),
    "list_int": (
        pa.array([[1, 2], [], None], pa.list_(pa.int64())),
        pa.array([[9, None], None], pa.list_(pa.int64())),
        pa.array([[0], [1, 2, 3]], pa.list_(pa.int64())),
    ),
    "struct": (
        pa.array([{"a": 1, "b": "s"}, {"a": None, "b": None}, None], STRUCT_T),
        pa.array([{"a": 9, "b": "t"}, None], STRUCT_T),
        pa.array([{"a": 2, "b": None}, {"a": None, "b": "u"}], STRUCT_T),
    ),
    "map": (
        pa.array([[("k", 1)], [], None], pa.map_(pa.string(), pa.int64())),
        pa.array([[("z", 9), ("y", None)], None], pa.map_(pa.string(), pa.int64())),
        pa.array([[("a", 0)], [("b", 1)]], pa.map_(pa.string(), pa.int64())),
    ),
    "list_of_struct": (
        pa.array([[{"a": 1, "b": "x"}], [], None], pa.list_(STRUCT_T)),
        pa.array([[{"a": 9, "b": None}, None], None], pa.list_(STRUCT_T)),
        pa.array([[{"a": 2, "b": "y"}], [{"a": None, "b": None}]], pa.list_(STRUCT_T)),
    ),
    "deeply_nullable_nested": (
        pa.array(
            [
                {"inner": {"n": 1, "s": "a"}, "tags": ["t1", None]},
                {"inner": None, "tags": None},
                None,
            ],
            DEEP_T,
        ),
        pa.array([{"inner": {"n": None, "s": None}, "tags": []}, None], DEEP_T),
        pa.array([None, {"inner": None, "tags": [None]}], DEEP_T),
    ),
}


@pytest.mark.parametrize("case", VALUE_CASES, ids=list(VALUE_CASES))
def test_value_column_type_parity(case, tmp_path):
    init, upd1, upd2 = VALUE_CASES[case]
    uri_m, uri_u = _dual(tmp_path, case, _val_table(["a", "b", "c"], init))
    batches = [
        _val_table(["b", "d"], upd1),  # update one existing + insert one
        _val_table(["a", "d"], upd2),  # forces reading back deltalite-written files
    ]
    _assert_type_parity(uri_m, uri_u, batches, ["id"], case)


def test_null_typed_column_deltalite_errors_where_merge_succeeds(tmp_path):
    """FINDING (executable): a `pa.null()` column becomes Delta type 'void' at create
    time. MERGE handles the table; deltalite fails to open a writer for it
    ("Kernel error: Unsupported Delta table type: 'void'", surfaced from
    `RecordBatchWriter::for_table` in src/upsert.rs). Pinned so a fix is loud.
    """
    import deltalite

    init = _val_table(["a", "b"], pa.array([None, None], pa.null()))
    uri_m, uri_u = _dual(tmp_path, "null_typed", init)
    batch = _val_table(["b", "c"], pa.array([None, None], pa.null()))

    merge_path(uri_m, batch, ["id"], PARTITION_KEY)  # MERGE is fine with it
    assert len(read_sorted(uri_m)[0]) == 3

    with pytest.raises(deltalite.DeltaLiteError, match="void"):
        upsert_path(uri_u, batch, ["id"], PARTITION_KEY)
    assert deltalake.DeltaTable(uri_u).version() == 0  # nothing committed


# --------------------------------------------------------------------------------------
# Primary-key columns: the type under test IS the PK.
# --------------------------------------------------------------------------------------


def _pk_table(keys, key_type, v):
    n = len(keys)
    return pa.table(
        {
            "k": pa.array(keys, key_type) if key_type is not None else keys,
            "v": pa.array([v] * n, pa.int64()),
            PARTITION_KEY: pa.array(["2026-07-23"] * n, pa.string()),
        }
    )


# (type, initial keys, batch keys) -- batch overlaps initial so both a match and an
# insert are exercised; a NULL key is included where the type admits one, pinning the
# NULL-never-matches rule per type.
PK_CASES = {
    "int8": (pa.int8(), [1, 2, None], [2, 3, None]),
    "int16": (pa.int16(), [1, -2, None], [-2, 3, None]),
    "int32": (pa.int32(), [1, 2, None], [2, 3, None]),
    "int64": (pa.int64(), [2**40, -(2**40), None], [2**40, 3, None]),
    "bool": (pa.bool_(), [True, False], [True]),
    "float32": (pa.float32(), [1.5, 2.5, None], [2.5, 3.5, None]),
    "float64": (pa.float64(), [1.5, 2.5, None], [2.5, 3.5, None]),
    "binary": (pa.binary(), [b"\x00a", b"b", None], [b"b", b"c", None]),
    "large_string": (pa.large_string(), ["a", "b", None], ["b", "c", None]),
    "date32": (
        pa.date32(),
        [datetime.date(2026, 1, 1), datetime.date(2026, 1, 2), None],
        [datetime.date(2026, 1, 2), datetime.date(2026, 1, 3), None],
    ),
    "timestamp": (
        pa.timestamp("us"),
        [TS, TS + datetime.timedelta(seconds=1), None],
        [TS, TS + datetime.timedelta(days=1), None],
    ),
    "timestamp_tz": (
        pa.timestamp("us", tz="UTC"),
        [TS.replace(tzinfo=UTC), None],
        [TS.replace(tzinfo=UTC), TS.replace(tzinfo=UTC) + datetime.timedelta(days=1), None],
    ),
    "decimal128": (
        pa.decimal128(10, 2),
        [D("1.10"), D("2.20"), None],
        [D("2.20"), D("-3.30"), None],
    ),
    "decimal_wide": (
        pa.decimal128(38, 10),
        [D("12345678901234567890.0123456789"), None],
        [D("12345678901234567890.0123456789"), D("1.5"), None],
    ),
}


@pytest.mark.parametrize("case", PK_CASES, ids=list(PK_CASES))
def test_pk_type_parity(case, tmp_path):
    key_type, init_keys, batch_keys = PK_CASES[case]
    uri_m, uri_u = _dual(tmp_path, case, _pk_table(init_keys, key_type, 1))
    _assert_type_parity(uri_m, uri_u, [_pk_table(batch_keys, key_type, 2)], ["k"], case)


def test_pk_dictionary_encoded_parity(tmp_path):
    """A dictionary-encoded PK column must probe against plain-encoded target files."""
    init = _pk_table(pa.array(["a", "b"]).dictionary_encode(), None, 1)
    uri_m, uri_u = _dual(tmp_path, "pk_dict", init)
    batch = _pk_table(pa.array(["b", "c"]).dictionary_encode(), None, 2)
    _assert_type_parity(uri_m, uri_u, [batch], ["k"], "pk_dict")


def test_composite_pk_mixed_types_parity(tmp_path):
    """Composite PK across (string, int64, timestamp) with a NULL in each component."""

    def mk(rows, v):
        return pa.table(
            {
                "s": pa.array([r[0] for r in rows], pa.string()),
                "n": pa.array([r[1] for r in rows], pa.int64()),
                "t": pa.array([r[2] for r in rows], pa.timestamp("us")),
                "v": pa.array([v] * len(rows), pa.int64()),
                PARTITION_KEY: pa.array(["2026-07-23"] * len(rows), pa.string()),
            }
        )

    init = mk([("a", 1, TS), ("a", 2, TS), (None, 1, TS), ("b", None, TS), ("c", 1, None)], 1)
    batch = mk([("a", 2, TS), ("a", 3, TS), (None, 1, TS), ("b", None, TS), ("c", 1, None)], 2)
    uri_m, uri_u = _dual(tmp_path, "mixed_composite", init)
    _assert_type_parity(uri_m, uri_u, [batch], ["s", "n", "t"], "mixed_composite")


# --------------------------------------------------------------------------------------
# Float PK sharp edges, pinned ABSOLUTELY on both paths (cross-path equality alone
# cannot catch both being wrong the same way). The design flagged these as a risk;
# measured behavior is that the two paths agree:
#   * -0.0 does NOT match 0.0 (both treat them as distinct keys -> insert);
#   * NaN DOES match NaN (both treat NaN as equal to itself -> update).
# --------------------------------------------------------------------------------------


def _float_content(uri):
    tbl = deltalake.DeltaTable(uri).to_pyarrow_table()
    ks = [str(k) for k in tbl["k"].to_pylist()]  # str() distinguishes -0.0 from 0.0
    return sorted(zip(ks, tbl["v"].to_pylist()))


@pytest.mark.parametrize("path_name", ["merge", "upsert"])
def test_float_pk_negative_zero_absolute(tmp_path, path_name):
    path = merge_path if path_name == "merge" else upsert_path
    uri = str(tmp_path / f"negzero_{path_name}")
    create_table(uri, _pk_table([0.0, 1.5], pa.float64(), 1), True)

    path(uri, _pk_table([-0.0], pa.float64(), 2), ["k"], PARTITION_KEY)

    # -0.0 is a DISTINCT key: it inserts, and the 0.0 row is untouched
    assert _float_content(uri) == [("-0.0", 2), ("0.0", 1), ("1.5", 1)]


@pytest.mark.parametrize("path_name", ["merge", "upsert"])
def test_float_pk_nan_absolute(tmp_path, path_name):
    path = merge_path if path_name == "merge" else upsert_path
    uri = str(tmp_path / f"nan_{path_name}")
    create_table(uri, _pk_table([float("nan"), 1.5], pa.float64(), 1), True)

    path(uri, _pk_table([float("nan")], pa.float64(), 2), ["k"], PARTITION_KEY)

    # NaN MATCHES the existing NaN row: update, no duplicate NaN row
    assert _float_content(uri) == [("1.5", 1), ("nan", 2)]


@pytest.mark.parametrize("path_name", ["merge", "upsert"])
def test_float_pk_infinities_absolute(tmp_path, path_name):
    path = merge_path if path_name == "merge" else upsert_path
    uri = str(tmp_path / f"inf_{path_name}")
    create_table(uri, _pk_table([float("inf"), float("-inf")], pa.float64(), 1), True)

    path(uri, _pk_table([float("inf"), 0.5], pa.float64(), 2), ["k"], PARTITION_KEY)

    assert _float_content(uri) == [("-inf", 1), ("0.5", 2), ("inf", 2)]
