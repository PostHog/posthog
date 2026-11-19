"""Map Arrow types onto Postgres column types.

STRICT keeps the batch exports mapping, which raises on any type outside the event and person
shapes. PERMISSIVE keeps the warehouse sources mapping, which stores every type somehow: nested
values go to JSONB and unknown types go to TEXT.
"""

import re
from collections.abc import Mapping

import pyarrow as pa

from posthog.dataclasses import frozen

from products.warehouse_destinations.backend.core.json_type import JsonType
from products.warehouse_destinations.backend.destinations.postgres.errors import (
    ColumnTypeMappingError,
    PostgreSQLInvalidTargetError,
)
from products.warehouse_destinations.backend.facade.enums import TypePolicy


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

# Overrides go into DDL as SQL text, so only known type names, a numeric modifier, a time zone
# clause and array brackets can pass.
_BASE_TYPES = (
    "SMALLINT|INTEGER|INT|INT2|INT4|INT8|BIGINT|REAL|FLOAT4|FLOAT8|DOUBLE PRECISION|NUMERIC|DECIMAL|"
    "BOOLEAN|BOOL|TEXT|VARCHAR|CHARACTER VARYING|CHARACTER|CHAR|BYTEA|DATE|TIME|TIMETZ|TIMESTAMP|"
    "TIMESTAMPTZ|INTERVAL|JSON|JSONB|UUID|INET|CIDR|MACADDR|MONEY|XML"
)
_OVERRIDE_TYPE_PATTERN = re.compile(
    rf"(?:{_BASE_TYPES})(?: ?\(\d{{1,4}}(?: ?, ?\d{{1,4}})?\))?(?: WITH(?:OUT)? TIME ZONE)?(?:\[\])*",
    re.IGNORECASE,
)


def is_nested_type(arrow_type: pa.DataType) -> bool:
    return (
        pa.types.is_list(arrow_type)
        or pa.types.is_large_list(arrow_type)
        or pa.types.is_struct(arrow_type)
        or pa.types.is_map(arrow_type)
    )


def validate_override_type(column: str, column_type: str) -> str:
    """Return `column_type` with its whitespace collapsed, or raise when it is not an allowed type."""
    normalized = " ".join(column_type.split())
    if not _OVERRIDE_TYPE_PATTERN.fullmatch(normalized):
        raise PostgreSQLInvalidTargetError(f"Column override for '{column}' is not an allowed Postgres type")
    return normalized


def strict_type_for(name: str, arrow_type: pa.DataType) -> str:
    if isinstance(arrow_type, JsonType):
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
    if isinstance(arrow_type, JsonType):
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
    schema: pa.Schema, type_policy: TypePolicy, column_overrides: Mapping[str, str]
) -> tuple[PostgresColumn, ...]:
    """Return the Postgres column for each field of `schema`.

    An override wins over the policy for its column. Every override is validated, also when its
    column is not in `schema`.
    """
    overrides = {name: validate_override_type(name, value) for name, value in column_overrides.items()}

    columns = []
    for field in schema:
        if field.name in overrides:
            column_type = overrides[field.name]
        elif type_policy == TypePolicy.STRICT:
            column_type = strict_type_for(field.name, field.type)
        else:
            column_type = permissive_type_for(field.type)
        columns.append(PostgresColumn(name=field.name, type=column_type))
    return tuple(columns)
