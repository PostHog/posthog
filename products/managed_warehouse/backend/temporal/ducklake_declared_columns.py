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

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from posthog.dataclasses import frozen

# The type for a declared ClickHouse type that has no exact Trino or DuckDB type. Every row of such a column is NULL,
# so no value is lost.
FALLBACK_TYPE = "VARCHAR"
_MAX_DECIMAL_PRECISION = 38
_WRAPPER_PATTERN = re.compile(r"^(?:Nullable|LowCardinality)\((.*)\)$")
_DATETIME_PATTERN = re.compile(r"^DateTime(?:64)?(?:\((.*)\))?$")
_DECIMAL_PATTERN = re.compile(r"^Decimal\(\s*(\d+)\s*(?:,\s*(\d+)\s*)?\)$")
_SIZED_DECIMAL_PATTERN = re.compile(r"^Decimal(32|64|128|256)\(\s*(\d+)\s*\)$")
_SIZED_DECIMAL_PRECISION = {"32": 9, "64": 18, "128": 38, "256": 76}


@frozen
class DeclaredColumn:
    name: str
    clickhouse_type: str


@frozen
class _DuckLakeType:
    trino: str
    duckdb: str


# Each type is the one that the Arrow type of the same data maps to on the registration paths, so a column has the
# same type when a later sync writes values for it. Trino has no unsigned integer type, so an unsigned column uses
# the fallback type there.
_SCALAR_TYPES: dict[str, _DuckLakeType] = {
    "String": _DuckLakeType(trino="VARCHAR", duckdb="VARCHAR"),
    "Int8": _DuckLakeType(trino="TINYINT", duckdb="TINYINT"),
    "Int16": _DuckLakeType(trino="SMALLINT", duckdb="SMALLINT"),
    "Int32": _DuckLakeType(trino="INTEGER", duckdb="INTEGER"),
    "Int64": _DuckLakeType(trino="BIGINT", duckdb="BIGINT"),
    "UInt8": _DuckLakeType(trino=FALLBACK_TYPE, duckdb="UTINYINT"),
    "UInt16": _DuckLakeType(trino=FALLBACK_TYPE, duckdb="USMALLINT"),
    "UInt32": _DuckLakeType(trino=FALLBACK_TYPE, duckdb="UINTEGER"),
    "UInt64": _DuckLakeType(trino=FALLBACK_TYPE, duckdb="UBIGINT"),
    "Float32": _DuckLakeType(trino="REAL", duckdb="FLOAT"),
    "Float64": _DuckLakeType(trino="DOUBLE", duckdb="DOUBLE"),
    "Bool": _DuckLakeType(trino="BOOLEAN", duckdb="BOOLEAN"),
    "Date": _DuckLakeType(trino="DATE", duckdb="DATE"),
    "Date32": _DuckLakeType(trino="DATE", duckdb="DATE"),
}
_FALLBACK = _DuckLakeType(trino=FALLBACK_TYPE, duckdb=FALLBACK_TYPE)


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
    return _ducklake_type(clickhouse_type).trino


def duckdb_type_for_clickhouse(clickhouse_type: str) -> str:
    return _ducklake_type(clickhouse_type).duckdb


def _ducklake_type(clickhouse_type: str) -> _DuckLakeType:
    base = clickhouse_type.strip()
    while (wrapper := _WRAPPER_PATTERN.fullmatch(base)) is not None:
        base = wrapper.group(1).strip()

    if (scalar := _SCALAR_TYPES.get(base)) is not None:
        return scalar
    if (datetime := _DATETIME_PATTERN.fullmatch(base)) is not None:
        # A ClickHouse time zone argument is a quoted string, as in DateTime64(6, 'UTC'). The precision is always 6
        # because the registration paths read only microsecond timestamps from the files.
        if "'" in (datetime.group(1) or ""):
            return _DuckLakeType(trino="TIMESTAMP(6) WITH TIME ZONE", duckdb="TIMESTAMPTZ")
        return _DuckLakeType(trino="TIMESTAMP(6)", duckdb="TIMESTAMP")
    if (decimal := _DECIMAL_PATTERN.fullmatch(base)) is not None:
        return _decimal_type(int(decimal.group(1)), int(decimal.group(2) or 0))
    if (sized_decimal := _SIZED_DECIMAL_PATTERN.fullmatch(base)) is not None:
        return _decimal_type(_SIZED_DECIMAL_PRECISION[sized_decimal.group(1)], int(sized_decimal.group(2)))
    return _FALLBACK


def _decimal_type(precision: int, scale: int) -> _DuckLakeType:
    if not 1 <= precision <= _MAX_DECIMAL_PRECISION or not 0 <= scale <= precision:
        return _FALLBACK
    decimal_type = f"DECIMAL({precision}, {scale})"
    return _DuckLakeType(trino=decimal_type, duckdb=decimal_type)
