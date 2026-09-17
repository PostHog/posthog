"""Mapping Arrow types onto SQL column types.

Kept apart from any one writer because the mappings differ per dialect but the decisions do
not: prefer the widest sensible type, and fall back to JSON for anything nested rather than
flattening it, so a column that is a struct today and a wider struct tomorrow keeps working.
"""

from __future__ import annotations

import pyarrow as pa

_POSTGRES_BY_ARROW_ID = {
    pa.bool_(): "BOOLEAN",
    pa.int8(): "SMALLINT",
    pa.int16(): "SMALLINT",
    pa.int32(): "INTEGER",
    pa.int64(): "BIGINT",
    pa.uint8(): "SMALLINT",
    pa.uint16(): "INTEGER",
    pa.uint32(): "BIGINT",
    # No unsigned 64-bit integer in Postgres; NUMERIC keeps the full range rather than
    # overflowing BIGINT at half the values.
    pa.uint64(): "NUMERIC",
    pa.float16(): "REAL",
    pa.float32(): "REAL",
    pa.float64(): "DOUBLE PRECISION",
    pa.string(): "TEXT",
    pa.large_string(): "TEXT",
    pa.binary(): "BYTEA",
    pa.large_binary(): "BYTEA",
    pa.date32(): "DATE",
    pa.date64(): "DATE",
}


def is_nested_type(arrow_type: pa.DataType) -> bool:
    """Whether an Arrow type holds a nested value, which every dialect here stores as JSON."""
    return (
        pa.types.is_list(arrow_type)
        or pa.types.is_large_list(arrow_type)
        or pa.types.is_struct(arrow_type)
        or pa.types.is_map(arrow_type)
    )


def postgres_type_for(arrow_type: pa.DataType) -> str:
    """The Postgres column type for an Arrow type."""
    mapped = _POSTGRES_BY_ARROW_ID.get(arrow_type)
    if mapped is not None:
        return mapped

    if pa.types.is_timestamp(arrow_type):
        return "TIMESTAMPTZ" if arrow_type.tz else "TIMESTAMP"
    if pa.types.is_time(arrow_type):
        return "TIME"
    if pa.types.is_decimal(arrow_type):
        return f"NUMERIC({arrow_type.precision}, {arrow_type.scale})"
    if pa.types.is_duration(arrow_type):
        return "INTERVAL"
    if is_nested_type(arrow_type):
        return "JSONB"

    # An unrecognized type is stored as text rather than failing the sync. The value survives,
    # and the column can be widened later without another full re-sync.
    return "TEXT"


def quote_identifier(name: str) -> str:
    """Quote an identifier for a dialect that uses double quotes."""
    escaped = name.replace('"', '""')
    return f'"{escaped}"'
