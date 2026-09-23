import pytest
from unittest import mock

import pyarrow as pa
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.batcher import (
    Batcher,
    _column_offset_pressure,
    _max_offset_pressure,
    _split_table,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.table_stats import (
    _column_payload_bytes,
    table_payload_bytes,
)


def _split_to_offset_limit(table: pa.Table, *, limit: int) -> list[pa.Table]:
    """Offset-only split shim for the existing tests below (byte cap effectively off)."""
    return _split_table(table, offset_limit=limit, bytes_limit=2**62)


def _drain(batcher: Batcher) -> list[pa.Table]:
    tables = []
    while batcher.should_yield(include_incomplete_chunk=True):
        tables.append(batcher.get_table())
    return tables


def test_batching_pa_table_should_yield():
    batcher = Batcher(logger=mock.MagicMock())

    pa_table = pa.table(
        {
            "column1": [1, 2, 3],
            "column2": ["a", "b", "c"],
        }
    )

    batcher.batch(pa_table)

    assert batcher.should_yield() is True

    result_table = batcher.get_table()

    assert result_table.equals(pa_table)


def test_batching_multiple_pa_tables_should_raise():
    batcher = Batcher(logger=mock.MagicMock())

    pa_table1 = pa.table(
        {
            "column1": [1, 2, 3],
            "column2": ["a", "b", "c"],
        }
    )

    pa_table2 = pa.table(
        {
            "column1": [4, 5, 6],
            "column2": ["d", "e", "f"],
        }
    )

    batcher.batch(pa_table1)

    with pytest.raises(Exception) as exc_info:
        batcher.batch(pa_table2)

    assert (
        str(exc_info.value)
        == "Batcher already has a table ready to yield. Call get_table() before batching more items."
    )


def test_batching_lists_should_yield_after_chunk_size_threshold():
    batcher = Batcher(logger=mock.MagicMock(), chunk_size=3)

    list_data = [{"a": 1}, {"a": 2}, {"a": 3}]
    batcher.batch(list_data)

    assert batcher.should_yield() is True

    result_table = batcher.get_table()
    expected_table = pa.table({"a": [1, 2, 3]})

    assert result_table.equals(expected_table)


def test_batching_lists_should_yield_after_chunk_size_bytes_threshold():
    batcher = Batcher(logger=mock.MagicMock(), chunk_size_bytes=1)

    batcher.batch([{"a": "x"}, {"a": "y"}])

    assert batcher.should_yield() is True

    result_table = batcher.get_table()
    expected_table = pa.table({"a": ["x", "y"]})

    assert result_table.equals(expected_table)


@parameterized.expand(
    [
        ("string", pa.array(["aa", "bb", "cc", "dd"], type=pa.string()), 8),
        ("binary", pa.array([b"aa", b"bb"], type=pa.binary()), 4),
        ("list", pa.array([[1, 2], [3], [4, 5, 6]], type=pa.list_(pa.int64())), 6),
        ("large_string_is_safe", pa.array(["aa", "bb"], type=pa.large_string()), 0),
        ("int_is_safe", pa.array([1, 2, 3], type=pa.int64()), 0),
        ("nulls_counted_as_zero", pa.array([None, "abc", None], type=pa.string()), 3),
    ]
)
def test_column_offset_pressure(_name: str, array: pa.Array, expected: int):
    assert _column_offset_pressure(pa.chunked_array([array])) == expected


def test_max_offset_pressure_picks_worst_column():
    table = pa.table(
        {
            "small": pa.array(["a", "b"], type=pa.string()),
            "big": pa.array(["aaaa", "bbbb"], type=pa.string()),
            "ints": pa.array([1, 2], type=pa.int64()),
        }
    )

    assert _max_offset_pressure(table) == 8


def test_split_to_offset_limit_under_limit_is_noop():
    table = pa.table({"a": ["x", "y", "z"]})

    result = _split_to_offset_limit(table, limit=1_000)

    assert len(result) == 1
    assert result[0].equals(table)


def test_split_to_offset_limit_splits_and_preserves_data_and_order():
    table = pa.table({"id": [0, 1, 2, 3], "val": ["aa", "bb", "cc", "dd"]})

    # Total "val" bytes = 8; limit 3 forces splitting until each slice is <= 3 bytes.
    result = _split_to_offset_limit(table, limit=3)

    assert len(result) > 1
    for slice_table in result:
        assert _max_offset_pressure(slice_table) <= 3
    # Concatenating the slices reproduces the original table in order.
    assert pa.concat_tables(result).equals(table)


def test_split_to_offset_limit_single_row_never_splits():
    # A single row can't be split further even if it exceeds the limit.
    table = pa.table({"val": ["a-very-long-value"]})

    result = _split_to_offset_limit(table, limit=1)

    assert len(result) == 1
    assert result[0].equals(table)


def test_batcher_splits_oversized_pa_table_on_yield():
    batcher = Batcher(logger=mock.MagicMock(), max_column_offset_bytes=3)
    table = pa.table({"id": [0, 1, 2, 3], "val": ["aa", "bb", "cc", "dd"]})

    batcher.batch(table)

    drained = _drain(batcher)

    assert len(drained) > 1
    assert pa.concat_tables(drained).equals(table)


def test_batcher_does_not_split_when_under_limit():
    batcher = Batcher(logger=mock.MagicMock(), max_column_offset_bytes=1_000_000)
    table = pa.table({"id": [0, 1, 2, 3], "val": ["aa", "bb", "cc", "dd"]})

    batcher.batch(table)

    drained = _drain(batcher)

    assert len(drained) == 1
    assert drained[0].equals(table)


def test_batcher_splits_buffered_list_items():
    batcher = Batcher(logger=mock.MagicMock(), chunk_size=4, max_column_offset_bytes=3)

    batcher.batch([{"val": "aa"}, {"val": "bb"}, {"val": "cc"}, {"val": "dd"}])

    drained = _drain(batcher)

    assert len(drained) > 1
    combined = pa.concat_tables(drained)
    assert combined.column("val").to_pylist() == ["aa", "bb", "cc", "dd"]


@parameterized.expand(
    [
        # value bytes + 32-bit offset buffer (n * 4): 4 + 8 = 12
        ("string", pa.array(["aa", "bb"], type=pa.string()), 12),
        ("binary", pa.array([b"aa", b"bb"], type=pa.binary()), 12),
        # value bytes + 64-bit offset buffer (n * 8): 4 + 16 = 20
        ("large_string_counted", pa.array(["aa", "bb"], type=pa.large_string()), 20),
        ("large_binary_counted", pa.array([b"aa", b"bb"], type=pa.large_binary()), 20),
        # Lists recurse into their child values + 32-bit offset buffer (n * 4). Counting the child
        # *element count* instead (the old behaviour) undercounts a list of blobs by orders of
        # magnitude, which silently disables the byte-driven split for every source that maps a
        # repeated field to a list (e.g. Google Ads repeated protobuf messages -> JSON strings).
        # child 3 * int64 = 24; offsets 2 * 4 = 8
        ("list_of_int64", pa.array([[1, 2], [3]], type=pa.list_(pa.int64())), 32),
        # child strings 4+2+1 value bytes + 3 * 4 offsets = 19; list offsets 2 * 4 = 8
        ("list_of_string_counts_child_bytes", pa.array([["aaaa", "bb"], ["c"]], type=pa.list_(pa.string())), 27),
        # child "aa" = 2 + 1 * 4 = 6; large-list offsets 1 * 8 = 8
        ("large_list_uses_64_bit_offsets", pa.array([["aa"]], type=pa.large_list(pa.string())), 14),
        # child 4 * int64 = 32; fixed-size lists carry no offset buffer
        ("fixed_size_list_has_no_offsets", pa.array([[1, 2], [3, 4]], type=pa.list_(pa.int64(), 2)), 32),
        # struct child: "k" = 1 + 4 = 5, "vv" = 2 + 4 = 6; list offsets 1 * 4 = 4
        ("map_counted_via_key_value_struct", pa.array([[("k", "vv")]], type=pa.map_(pa.string(), pa.string())), 15),
        # struct child "aa" = 2 + 1 * 4 = 6; list offsets 1 * 4 = 4
        ("list_of_struct", pa.array([[{"s": "aa"}]], type=pa.list_(pa.struct([("s", pa.string())]))), 10),
        # No child values to measure, but the offset buffer is still resident
        ("all_null_list_counts_offsets_only", pa.array([None, None], type=pa.list_(pa.string())), 8),
        ("int64", pa.array([1, 2, 3], type=pa.int64()), 24),
        ("bool_subbyte_is_zero", pa.array([True, False, True], type=pa.bool_()), 0),
        ("nulls_counted_as_zero_payload", pa.array([None, "abc"], type=pa.string()), 3 + 8),
        # Struct now recurses into child fields (int64: 1*8=8; string "aa": 2 value + 1*4 offset = 6) so a
        # nested Mongo-style document under `data` is bounded by the byte split instead of counting as 0.
        (
            "struct_counts_child_payload",
            pa.array([{"x": 1, "s": "aa"}], type=pa.struct([("x", pa.int64()), ("s", pa.string())])),
            8 + 6,
        ),
    ]
)
def test_column_payload_bytes(_name: str, array: pa.Array, expected: int):
    assert _column_payload_bytes(pa.chunked_array([array])) == expected


def test_table_payload_bytes_is_slice_accurate():
    # Guards against a refactor reintroducing Array.nbytes, which reports the full shared
    # buffer for a zero-copy slice and would make the byte-driven split non-converging.
    table = pa.table({"val": ["aaaa", "bbbb", "cccc", "dddd"]})

    full = table_payload_bytes(table)
    first_half = table_payload_bytes(table.slice(0, 2))
    second_half = table_payload_bytes(table.slice(2, 2))

    assert first_half < full
    assert first_half == second_half  # equal-sized rows here


def test_split_table_splits_on_bytes_when_offset_is_under_limit():
    # Offset limit is huge, so only the byte cap can drive the split.
    table = pa.table({"val": ["aa", "bb", "cc", "dd"]})

    result = _split_table(table, offset_limit=1_000_000, bytes_limit=14)

    assert len(result) > 1
    for slice_table in result:
        assert table_payload_bytes(slice_table) <= 14 or slice_table.num_rows <= 1
    assert pa.concat_tables(result).equals(table)


def test_split_table_byte_cap_sums_across_columns():
    # Each column's payload (16) is under the limit, but their sum (32) exceeds it, so it must
    # still split. Guards against measuring the worst column (like the offset guard) instead of the total.
    table = pa.table({"a": ["aaaa", "bbbb"], "b": ["cccc", "dddd"]})

    result = _split_table(table, offset_limit=1_000_000, bytes_limit=20)

    assert len(result) > 1
    assert pa.concat_tables(result).equals(table)


def test_split_table_splits_a_list_column_on_its_child_bytes():
    # The shape that used to slip through: four rows holding ~4 KiB of strings inside a list column.
    # Measured by child element count the table scored 12 bytes and never split, so a chunk of these
    # grew to the row limit regardless of its real size and became the loader's merge memory.
    table = pa.table(
        {"val": pa.array([["x" * 1000], ["y" * 1000], ["z" * 1000], ["w" * 1000]], type=pa.list_(pa.string()))}
    )

    result = _split_table(table, offset_limit=1_000_000, bytes_limit=2048)

    assert len(result) > 1
    for slice_table in result:
        assert table_payload_bytes(slice_table) <= 2048 or slice_table.num_rows <= 1
    assert pa.concat_tables(result).equals(table)


def test_split_table_single_oversized_row_terminates():
    table = pa.table({"val": ["a-very-long-value"]})

    result = _split_table(table, offset_limit=1, bytes_limit=1)

    assert len(result) == 1
    assert result[0].equals(table)


def test_batcher_splits_oversized_pa_table_by_bytes_on_yield():
    batcher = Batcher(logger=mock.MagicMock(), max_table_bytes=14, max_column_offset_bytes=1_000_000)
    table = pa.table({"val": ["aa", "bb", "cc", "dd"]})

    batcher.batch(table)

    drained = _drain(batcher)

    assert len(drained) > 1
    assert pa.concat_tables(drained).equals(table)


def test_batcher_logs_when_splitting_by_bytes():
    logger = mock.MagicMock()
    batcher = Batcher(logger=logger, max_table_bytes=14, max_column_offset_bytes=1_000_000)

    batcher.batch(pa.table({"val": ["aa", "bb", "cc", "dd"]}))
    _drain(batcher)

    logger.info.assert_called_once()
    assert logger.info.call_args.args[0] == "batcher_split_by_bytes"


def test_batcher_does_not_log_byte_split_for_offset_only_split():
    # An offset-driven split (byte cap effectively off) must not emit the byte-split signal.
    logger = mock.MagicMock()
    batcher = Batcher(logger=logger, max_column_offset_bytes=3, max_table_bytes=10**12)

    batcher.batch(pa.table({"val": ["aa", "bb", "cc", "dd"]}))
    drained = _drain(batcher)

    assert len(drained) > 1  # it did split, by offset
    byte_events = [c for c in logger.info.call_args_list if c.args and c.args[0] == "batcher_split_by_bytes"]
    assert byte_events == []


def test_batcher_does_not_split_small_table_under_byte_cap():
    # Default byte cap (256 MiB) and offset cap; a tiny table stays a single chunk.
    batcher = Batcher(logger=mock.MagicMock())
    table = pa.table({"id": [0, 1, 2, 3], "val": ["aa", "bb", "cc", "dd"]})

    batcher.batch(table)

    drained = _drain(batcher)

    assert len(drained) == 1
    assert drained[0].equals(table)


def test_coalescing_pa_tables_accumulates_to_row_cap():
    batcher = Batcher(logger=mock.MagicMock(), chunk_size=10, coalesce_tables=True)

    tables = [pa.table({"id": [i * 2, i * 2 + 1]}) for i in range(6)]
    yielded = []
    for table in tables:
        batcher.batch(table)
        while batcher.should_yield():
            yielded.append(batcher.get_table())

    # 5 x 2-row tables buffer silently; the 5th reaches the 10-row cap and flushes as one batch.
    assert len(yielded) == 1
    assert yielded[0].num_rows == 10
    while batcher.should_yield(include_incomplete_chunk=True):
        yielded.append(batcher.get_table())
    combined = pa.concat_tables(yielded)
    assert combined.column("id").to_pylist() == list(range(12))


def test_coalescing_disabled_by_default_keeps_one_yield_one_batch():
    batcher = Batcher(logger=mock.MagicMock(), chunk_size=1_000)
    table = pa.table({"id": [1, 2]})

    batcher.batch(table)

    assert batcher.should_yield() is True
    assert batcher.get_table().equals(table)


def test_coalescing_flushes_buffer_before_byte_cap_is_exceeded():
    table = pa.table({"id": [1, 2], "val": ["aa", "bb"]})
    per_table = table_payload_bytes(table)
    # Cap fits 2 tables but not 3, so the 3rd must flush the buffer *without* joining it.
    cap = per_table * 2 + per_table // 2
    batcher = Batcher(logger=mock.MagicMock(), chunk_size_bytes=cap, coalesce_tables=True)

    batcher.batch(table)
    batcher.batch(table)
    assert batcher.should_yield() is False

    # The flushed batch stays within chunk_size_bytes (which keeps it under max_table_bytes,
    # so _split_table doesn't undo the coalescing) and the 3rd table starts the next buffer.
    batcher.batch(table)
    assert batcher.should_yield() is True
    flushed = batcher.get_table()
    assert flushed.num_rows == 4
    assert table_payload_bytes(flushed) <= cap

    assert batcher.should_yield(include_incomplete_chunk=True) is True
    assert batcher.get_table().equals(table)


def test_coalescing_oversized_single_table_flushes_alone_without_waiting():
    table = pa.table({"id": [1, 2], "val": ["aa", "bb"]})
    batcher = Batcher(logger=mock.MagicMock(), chunk_size_bytes=1, coalesce_tables=True)

    batcher.batch(table)

    assert batcher.should_yield() is True
    assert batcher.get_table().equals(table)


def test_coalescing_promotes_compatible_schema_drift():
    batcher = Batcher(logger=mock.MagicMock(), chunk_size=4, coalesce_tables=True)

    batcher.batch(pa.table({"a": pa.array([1, 2], pa.int64()), "b": ["x", "y"]}))
    batcher.batch(pa.table({"a": pa.array([1.5, 2.5], pa.float64())}))

    assert batcher.should_yield() is True
    flushed = batcher.get_table()
    assert flushed.num_rows == 4
    assert flushed.schema.field("a").type == pa.float64()
    assert flushed.column("b").to_pylist() == ["x", "y", None, None]


def test_coalescing_flushes_on_non_promotable_schema_drift():
    batcher = Batcher(logger=mock.MagicMock(), chunk_size=1_000, coalesce_tables=True)
    int_table = pa.table({"a": pa.array([1, 2], pa.int64())})
    str_table = pa.table({"a": pa.array(["x", "y"], pa.string())})

    batcher.batch(int_table)
    assert batcher.should_yield() is False

    # int64 -> string can't be promoted, so the buffered table flushes as-is and the
    # incompatible one starts a new buffer instead of crashing pa.concat_tables.
    batcher.batch(str_table)
    assert batcher.should_yield() is True
    assert batcher.get_table().equals(int_table)

    assert batcher.should_yield(include_incomplete_chunk=True) is True
    assert batcher.get_table().equals(str_table)


def test_coalescing_partial_buffer_flushes_at_end_of_stream():
    batcher = Batcher(logger=mock.MagicMock(), chunk_size=1_000, coalesce_tables=True)

    batcher.batch(pa.table({"id": [1, 2]}))
    batcher.batch(pa.table({"id": [3]}))

    # Below the caps nothing is ready, but the end-of-stream drain must still see and
    # flush the buffered tables; dropping them would silently lose the sync's tail.
    assert batcher.should_yield() is False
    assert batcher.should_yield(include_incomplete_chunk=True) is True
    assert batcher.get_table().column("id").to_pylist() == [1, 2, 3]
    assert batcher.should_yield(include_incomplete_chunk=True) is False


def test_batching_list_while_tables_buffered_raises():
    batcher = Batcher(logger=mock.MagicMock(), chunk_size=1_000, coalesce_tables=True)

    batcher.batch(pa.table({"id": [1]}))

    with pytest.raises(Exception, match="Cannot batch list/dict rows while pa.Tables are buffered"):
        batcher.batch([{"id": 2}])


def test_batching_should_not_yield_when_buffer_not_full():
    batcher = Batcher(logger=mock.MagicMock(), chunk_size=5, chunk_size_bytes=1000)

    batcher.batch([{"a": 1}, {"a": 2}])

    assert batcher.should_yield() is False


def test_batching_should_yield_when_buffer_not_full_with_incomplete_chunk_set():
    batcher = Batcher(logger=mock.MagicMock(), chunk_size=50, chunk_size_bytes=10000)

    batcher.batch({"a": 1})
    batcher.batch({"a": 2})
    batcher.batch({"a": 3})

    assert batcher.should_yield(include_incomplete_chunk=False) is False
    assert batcher.should_yield(include_incomplete_chunk=True) is True

    result_table = batcher.get_table()
    expected_table = pa.table({"a": [1, 2, 3]})

    assert result_table.equals(expected_table)


def test_batching_pa_table_converts_primary_key_binary_column_to_hex():
    batcher = Batcher(logger=mock.MagicMock(), primary_keys=["sk_load"])

    batcher.batch(
        pa.table(
            {
                "sk_load": pa.array([b"\xbd\xd6\x40", None], type=pa.binary()),
                "payload": pa.array([b"\x01", b"\x02"], type=pa.binary()),
            }
        )
    )

    result_table = batcher.get_table()

    assert result_table.column("sk_load").to_pylist() == ["bdd640", None]
    assert result_table.schema.field("sk_load").type == pa.string()
    assert result_table.column("payload").to_pylist() == [b"\x01", b"\x02"]
