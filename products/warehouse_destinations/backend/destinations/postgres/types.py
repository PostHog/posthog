"""Map Arrow types and logical types onto Postgres column types.

A type pinned in `TableTarget.column_types` wins. Otherwise STRICT maps the types below and
raises `ColumnTypeMappingError` (DATA kind) for any other type, and PERMISSIVE stores every
type: nested values go to JSONB and unknown types go to TEXT.

STRICT supports: JSON extension types, strings, integers, floats, booleans, timestamps and
lists of strings.
"""

from collections.abc import Mapping

import pyarrow as pa

from posthog.dataclasses import frozen

from products.warehouse_destinations.backend.core.json_type import is_json_type
from products.warehouse_destinations.backend.destinations.postgres.errors import ColumnTypeMappingError
from products.warehouse_destinations.backend.facade.enums import LogicalType, TypePolicy


@frozen
class PostgresColumn:
    name: str
    type: str


_PERMISSIVE_BY_ARROW_TYPE = {
    pa.bool_(): "BOOLEAN",
    pa.int8(): "SMALLINT",
    pa.int16(): "SMALLINT",
    pa.int32(): "INTEGER",
    pa.int64(): "BIGINT",
    pa.uint8(): "SMALLINT",
    pa.uint16(): "INTEGER",
    pa.uint32(): "BIGINT",
    # Postgres has no unsigned 64-bit integer. NUMERIC keeps the full range, and BIGINT overflows
    # at half of the values.
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
    return (
        pa.types.is_list(arrow_type)
        or pa.types.is_large_list(arrow_type)
        or pa.types.is_struct(arrow_type)
        or pa.types.is_map(arrow_type)
    )


_BY_LOGICAL_TYPE: dict[LogicalType, str] = {
    LogicalType.TEXT: "TEXT",
    LogicalType.BOOLEAN: "BOOLEAN",
    LogicalType.INT32: "INTEGER",
    LogicalType.INT64: "BIGINT",
    LogicalType.FLOAT64: "DOUBLE PRECISION",
    LogicalType.DECIMAL: "NUMERIC",
    LogicalType.DATE: "DATE",
    LogicalType.TIMESTAMP: "TIMESTAMP",
    LogicalType.TIMESTAMP_TZ: "TIMESTAMPTZ",
    LogicalType.JSON: "JSONB",
    LogicalType.BINARY: "BYTEA",
    LogicalType.UUID: "UUID",
}


def logical_type_for(logical_type: LogicalType, arrow_type: pa.DataType) -> str:
    """The Postgres type for `logical_type`. A DECIMAL keeps the precision of an Arrow decimal."""
    if logical_type == LogicalType.DECIMAL and pa.types.is_decimal(arrow_type):
        return f"NUMERIC({arrow_type.precision}, {arrow_type.scale})"
    return _BY_LOGICAL_TYPE[logical_type]


def strict_type_for(name: str, arrow_type: pa.DataType) -> str:
    if is_json_type(arrow_type):
        return "JSONB"
    if pa.types.is_string(arrow_type):
        return "TEXT"
    if pa.types.is_signed_integer(arrow_type) or pa.types.is_unsigned_integer(arrow_type):
        return "BIGINT" if pa.types.is_uint64(arrow_type) or pa.types.is_int64(arrow_type) else "INTEGER"
    if pa.types.is_floating(arrow_type):
        return "DOUBLE PRECISION" if pa.types.is_float64(arrow_type) else "REAL"
    if pa.types.is_boolean(arrow_type):
        return "BOOLEAN"
    if pa.types.is_timestamp(arrow_type):
        return "TIMESTAMPTZ" if arrow_type.tz is not None else "TIMESTAMP"
    if pa.types.is_list(arrow_type) and pa.types.is_string(arrow_type.value_type):
        return "TEXT[]"
    raise ColumnTypeMappingError("PostgreSQL", name, arrow_type)


def permissive_type_for(arrow_type: pa.DataType) -> str:
    if is_json_type(arrow_type):
        return "JSONB"

    mapped = _PERMISSIVE_BY_ARROW_TYPE.get(arrow_type)
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

    # Store an unknown type as text rather than fail the write. The value survives, and the
    # column can change type later.
    return "TEXT"


def resolve_columns(
    schema: pa.Schema, type_policy: TypePolicy, column_types: Mapping[str, LogicalType]
) -> tuple[PostgresColumn, ...]:
    """Return the Postgres column for each field of `schema`. A pinned type wins over the policy."""
    columns = []
    for field in schema:
        if field.name in column_types:
            column_type = logical_type_for(column_types[field.name], field.type)
        elif type_policy == TypePolicy.STRICT:
            column_type = strict_type_for(field.name, field.type)
        else:
            column_type = permissive_type_for(field.type)
        columns.append(PostgresColumn(name=field.name, type=column_type))
    return tuple(columns)
