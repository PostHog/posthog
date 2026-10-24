import json
import decimal
from collections.abc import Collection
from typing import TYPE_CHECKING, cast

import pyarrow as pa
import pyarrow.compute as pc

if TYPE_CHECKING:
    import duckdb

# Raise this when the normalization or the digest below changes. The writer stores it next to each
# hash, so a reader can tell an old hash apart from a current one and recompute it instead of
# reading every row as changed.
ROW_HASH_VERSION = 1
ROW_HASH_TYPE = pa.binary(16)

_FIELD_SEPARATOR = b"\x1f"
_BINARY = pa.large_binary()
# Wider than the 76 digits of the widest Arrow decimal, so normalizing never rounds a value.
_DECIMAL_CONTEXT = decimal.Context(prec=100)
# Rows encoded and hashed at a time, so the encoded copy stays bounded on a wide batch.
_HASH_SLICE_ROWS = 65_536


def compute_row_hashes(table: pa.Table, exclude_columns: Collection[str] = ()) -> pa.Array:
    """One 16-byte MD5 content hash per row of `table`, under `ROW_HASH_VERSION`.

    The hash covers the non-null values of every column outside `exclude_columns`. It does not
    depend on column order, on a numeric, decimal or temporal column changing width or unit, or on
    a column that holds null, so a schema change alone does not change the hash of a row.
    Values inside nested columns are not normalized beyond key order.

    MD5 is a fixed algorithm, so a stored hash stays comparable after a library upgrade. It is not
    used for security here.
    """
    import duckdb  # noqa: PLC0415 — keeps duckdb off the import path of every pipeline that loads the writer

    hashed_columns = [name for name in sorted(table.column_names) if name not in exclude_columns]
    # duckdb hashes a whole column in native code, which a Python loop over the rows cannot match.
    connection = duckdb.connect(config={"threads": 1})
    try:
        digests = [
            _slice_digests(connection, table.slice(offset, _HASH_SLICE_ROWS), hashed_columns)
            for offset in range(0, table.num_rows, _HASH_SLICE_ROWS)
        ]
    finally:
        connection.close()
    return pa.concat_arrays(digests) if digests else pa.array([], type=ROW_HASH_TYPE)


def _slice_digests(connection: "duckdb.DuckDBPyConnection", rows: pa.Table, hashed_columns: list[str]) -> pa.Array:
    pieces = [_named_values(name, rows.column(name)) for name in hashed_columns]
    if pieces:
        empty = pa.scalar(b"", _BINARY)
        # pyarrow's stubs do not accept a mix of arrays and a scalar separator.
        payloads = pc.binary_join_element_wise(  # type: ignore[call-overload]
            *pieces, empty, null_handling="replace", null_replacement=""
        )
    else:
        payloads = pa.array([b""] * rows.num_rows, type=_BINARY)

    connection.register("payloads", pa.table({"payload": payloads}))
    try:
        digests = connection.sql("SELECT unhex(md5(payload)) AS digest FROM payloads").to_arrow_table()
    finally:
        connection.unregister("payloads")
    return digests.column("digest").combine_chunks().cast(ROW_HASH_TYPE)


def _named_values(name: str, column: pa.ChunkedArray) -> pa.Array:
    values = _normalized_values(column.combine_chunks())
    # The length makes the encoding unambiguous: without it a value that contains the separator
    # and another column's name would hash the same as two separate values.
    lengths = pc.binary_length(cast(pa.LargeBinaryArray, values)).cast(pa.large_string()).cast(_BINARY)
    return pc.binary_join_element_wise(  # type: ignore[call-overload]
        pa.scalar(name.encode(), _BINARY), lengths, values, pa.scalar(_FIELD_SEPARATOR, _BINARY)
    )


def _normalized_values(values: pa.Array) -> pa.Array:
    """Encode each value as bytes that stay the same when only the column type changes."""
    arrow_type = values.type
    if pa.types.is_dictionary(arrow_type):
        values = values.cast(arrow_type.value_type)
        arrow_type = values.type

    if pa.types.is_decimal(arrow_type):
        # Arrow prints a decimal padded to its scale, and a small one in scientific notation, so the
        # same value prints as 1E-7 at scale 7 and as 1.0E-7 at scale 8. Fixed-point text of the
        # normalized value is the same at every scale.
        return pa.array(
            [
                None if value is None else format(_DECIMAL_CONTEXT.normalize(value), "f").encode()
                for value in values.to_pylist()
            ],
            type=_BINARY,
        )
    if pa.types.is_floating(arrow_type):
        return values.cast(pa.float64()).cast(pa.large_string()).cast(_BINARY)
    if pa.types.is_integer(arrow_type) or pa.types.is_boolean(arrow_type):
        return values.cast(pa.large_string()).cast(_BINARY)
    if pa.types.is_timestamp(arrow_type):
        microseconds = values.cast(pa.timestamp("us", tz=arrow_type.tz), safe=False).cast(pa.int64())
        return microseconds.cast(pa.large_string()).cast(_BINARY)
    if pa.types.is_date(arrow_type):
        return values.cast(pa.date32()).cast(pa.int32()).cast(pa.large_string()).cast(_BINARY)
    if pa.types.is_time(arrow_type):
        return values.cast(pa.time64("us"), safe=False).cast(pa.int64()).cast(pa.large_string()).cast(_BINARY)
    if (
        pa.types.is_string(arrow_type)
        or pa.types.is_large_string(arrow_type)
        or pa.types.is_string_view(arrow_type)
        or pa.types.is_binary(arrow_type)
        or pa.types.is_large_binary(arrow_type)
        or pa.types.is_binary_view(arrow_type)
        or pa.types.is_fixed_size_binary(arrow_type)
    ):
        return values.cast(_BINARY)

    return pa.array(
        [
            None if value is None else json.dumps(value, sort_keys=True, default=str).encode()
            for value in values.to_pylist()
        ],
        type=_BINARY,
    )
