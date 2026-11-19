"""The columns that a data import's table record declares, typed for DuckLake.

ClickHouse reads a data import with the column list in `DataWarehouseTable.columns` and reads a column that no file
carries as NULL. The sync writes no Parquet column for a column that is NULL in every row, so a table that DuckLake
builds from the files alone does not have that column, and a query that selects it fails there. The DuckLake
registration and copy paths add each declared column that the files do not carry, with the type below, so that
DuckLake also reads it as NULL.

A column that the files carry keeps the file type. The declared type only applies while no file carries the column,
and each registration and copy builds its table again from the files of that sync. Thus, when a later sync writes
values for the column, the table of that sync takes the file type, and the declared type of an earlier sync cannot
conflict with it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from posthog.hogql.type_system import RuntimeType, parse_clickhouse_type

from posthog.dataclasses import frozen

# The type for a declared ClickHouse type that has no exact Trino or DuckDB type. Every row of such a column is NULL,
# so no value is lost.
FALLBACK_TYPE = "VARCHAR"
_MAX_DECIMAL_PRECISION = 38
_SIGNED_INTEGER_TYPES = {8: "TINYINT", 16: "SMALLINT", 32: "INTEGER", 64: "BIGINT"}
_FLOAT_TYPES = {32: "REAL", 64: "DOUBLE"}
_TIMESTAMP_WITH_TIME_ZONE = "TIMESTAMP(6) WITH TIME ZONE"


@frozen
class DeclaredColumn:
    name: str
    clickhouse_type: str


def declared_columns(columns: Mapping[str, Any] | None) -> list[DeclaredColumn]:
    """Read the declared columns from a `DataWarehouseTable.columns` value."""
    declared: list[DeclaredColumn] = []
    for name, definition in (columns or {}).items():
        if isinstance(definition, str):
            clickhouse_type = definition
        elif isinstance(definition, Mapping):
            # ClickHouse leaves a column marked invalid out of the read by default, so DuckLake leaves it out too.
            if not definition.get("valid", True):
                continue
            clickhouse_type = str(definition.get("clickhouse") or "")
        else:
            continue
        declared.append(DeclaredColumn(name=name, clickhouse_type=clickhouse_type))
    return declared


def columns_missing_from_files(declared: Sequence[DeclaredColumn], file_columns: Iterable[str]) -> list[DeclaredColumn]:
    """The declared columns that no file column has, in declaration order.

    Trino and DuckDB fold identifiers to lower case, so the names are compared without case, and of two declared
    names that differ only in case the first is kept.
    """
    seen = {name.lower() for name in file_columns}
    missing: list[DeclaredColumn] = []
    for column in declared:
        key = column.name.lower()
        if key in seen:
            continue
        seen.add(key)
        missing.append(column)
    return missing


def trino_type_for_clickhouse(clickhouse_type: str) -> str:
    """The Trino type that reads like the ClickHouse type, or VARCHAR when no exact type exists.

    Each type is the one that the Arrow type of the same data maps to on the registration paths, so a column has the
    same type when a later sync writes values for it. Trino has no unsigned integer type, and the nested types have
    no exact match, so those use the fallback type.
    """
    runtime_type = parse_clickhouse_type(clickhouse_type)
    match runtime_type.family:
        case "integer" if runtime_type.signed:
            return _SIGNED_INTEGER_TYPES.get(runtime_type.bits or 0, FALLBACK_TYPE)
        case "float":
            return _FLOAT_TYPES.get(runtime_type.bits or 0, FALLBACK_TYPE)
        case "boolean":
            return "BOOLEAN"
        case "date":
            return "DATE"
        case "datetime":
            # The precision is always 6, because the registration paths read only microsecond timestamps.
            return _TIMESTAMP_WITH_TIME_ZONE if runtime_type.timezone else "TIMESTAMP(6)"
        case "decimal":
            return _decimal_type(runtime_type)
        case _:
            return FALLBACK_TYPE


def duckdb_type_for_clickhouse(clickhouse_type: str) -> str:
    """The DuckDB type for the same column.

    DuckDB accepts the Trino type names, except that it takes no precision on a time zone timestamp.
    """
    trino_type = trino_type_for_clickhouse(clickhouse_type)
    return "TIMESTAMPTZ" if trino_type == _TIMESTAMP_WITH_TIME_ZONE else trino_type


def _decimal_type(runtime_type: RuntimeType) -> str:
    precision, scale = runtime_type.precision, runtime_type.scale or 0
    if precision is None or not 1 <= precision <= _MAX_DECIMAL_PRECISION or not 0 <= scale <= precision:
        return FALLBACK_TYPE
    return f"DECIMAL({precision}, {scale})"
