"""Binlog row values typed the way a snapshot of the same table types them.

The snapshot types each column from `information_schema` through `MySQLColumn.to_arrow_field`. The binlog
names a column's wire type instead, so it is mapped to the `information_schema` type that produces it,
and the values the binlog decodes differently (JSON documents, SETs, BIT strings) are converted to what
the snapshot reads.
"""

from __future__ import annotations

import json
import decimal
import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pyarrow as pa
from pymysqlreplication.column import Column as BinlogColumn
from pymysqlreplication.constants import FIELD_TYPE, NONE_SOURCE

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import _is_id_like_column
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql import MySQLColumn

_BINARY_CHARSET = "binary"

_DATA_TYPES: dict[int, str] = {
    FIELD_TYPE.TINY: "tinyint",
    FIELD_TYPE.SHORT: "smallint",
    FIELD_TYPE.INT24: "mediumint",
    FIELD_TYPE.LONG: "int",
    FIELD_TYPE.LONGLONG: "bigint",
    FIELD_TYPE.DECIMAL: "decimal",
    FIELD_TYPE.NEWDECIMAL: "decimal",
    FIELD_TYPE.FLOAT: "float",
    FIELD_TYPE.DOUBLE: "double",
    FIELD_TYPE.DATE: "date",
    FIELD_TYPE.NEWDATE: "date",
    FIELD_TYPE.DATETIME: "datetime",
    FIELD_TYPE.DATETIME2: "datetime",
    FIELD_TYPE.TIMESTAMP: "timestamp",
    FIELD_TYPE.TIMESTAMP2: "timestamp",
    FIELD_TYPE.TIME: "time",
    FIELD_TYPE.TIME2: "time",
    FIELD_TYPE.YEAR: "year",
    FIELD_TYPE.JSON: "json",
    FIELD_TYPE.ENUM: "enum",
    FIELD_TYPE.SET: "set",
    FIELD_TYPE.BIT: "bit",
    FIELD_TYPE.GEOMETRY: "geometry",
}
_STRING_TYPES = (FIELD_TYPE.VARCHAR, FIELD_TYPE.VAR_STRING, FIELD_TYPE.STRING)
_TIMESTAMP_TYPES = (FIELD_TYPE.TIMESTAMP, FIELD_TYPE.TIMESTAMP2)
# pymysql reads these as bytes, which a snapshot hex-encodes or drops.
_BINARY_DATA_TYPES = frozenset({"varbinary", "blob", "bit", "geometry"})
_BLOB_TYPES = (FIELD_TYPE.BLOB, FIELD_TYPE.TINY_BLOB, FIELD_TYPE.MEDIUM_BLOB, FIELD_TYPE.LONG_BLOB)


def _data_type(column: BinlogColumn) -> str:
    binary = getattr(column, "character_set_name", None) == _BINARY_CHARSET
    if column.type in _STRING_TYPES:
        return "varbinary" if binary else "varchar"
    if column.type in _BLOB_TYPES:
        return "blob" if binary else "text"
    return _DATA_TYPES.get(column.type, "varchar")


def _mysql_column(column: BinlogColumn) -> MySQLColumn:
    data_type = _data_type(column)
    is_decimal = data_type == "decimal"
    return MySQLColumn(
        name=column.name,
        data_type=data_type,
        column_type=f"{data_type} unsigned" if getattr(column, "unsigned", False) else data_type,
        # The binlog doesn't carry nullability the way `information_schema` reports it, and a merge
        # widens a column to nullable anyway.
        nullable=True,
        numeric_precision=getattr(column, "precision", None) if is_decimal else None,
        numeric_scale=getattr(column, "decimals", None) if is_decimal else None,
    )


def _json_ready(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, Mapping):
        return {_json_ready(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, dt.date | dt.datetime | dt.time):
        return value.isoformat()
    return value


def _as_string(value: Any, column: BinlogColumn) -> str:
    if column.type == FIELD_TYPE.JSON:
        # MySQL returns a JSON column as JSON text, so a scalar keeps its quotes and `true` stays lowercase.
        return json.dumps(_json_ready(value), ensure_ascii=False)
    if isinstance(value, str):
        return value
    if isinstance(value, set | frozenset):
        # MySQL lists a SET's members in the order the column defines them.
        order = list(getattr(column, "set_values", None) or [])
        return ",".join(sorted(value, key=lambda member: order.index(member) if member in order else len(order)))
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _as_bytes(value: Any) -> bytes:
    if isinstance(value, str):
        # The library decodes a BIT column as a string of bits.
        return int(value or "0", 2).to_bytes(max((len(value) + 7) // 8, 1), "big")
    return bytes(value)


def _key_list(primary_key: Sequence[str] | str | None) -> list[str]:
    if isinstance(primary_key, str):
        return [primary_key] if primary_key else []
    return list(primary_key or [])


@dataclass(frozen=True)
class TableColumns:
    """One table map's columns: their Arrow types and how to convert a decoded row to them.

    A snapshot keeps a binary column only when it looks like a key, as lowercase hex, and drops the rest, so
    the binlog's binary and BIT values follow the same rule.
    """

    source: Sequence[BinlogColumn]
    arrow_types: Mapping[str, pa.DataType]
    primary_key: list[str]
    _by_name: Mapping[str, BinlogColumn]
    _hex_columns: frozenset[str]
    _dropped_columns: frozenset[str]

    @classmethod
    def from_binlog(cls, columns: Sequence[BinlogColumn], primary_key: Sequence[str] | str | None) -> TableColumns:
        keys = _key_list(primary_key)
        binary = {column.name for column in columns if _data_type(column) in _BINARY_DATA_TYPES}
        hex_columns = frozenset(name for name in binary if _is_id_like_column(name, keys))
        dropped = frozenset(binary - hex_columns)
        arrow_types = {
            column.name: pa.string() if column.name in hex_columns else _mysql_column(column).to_arrow_field().type
            for column in columns
            if column.name not in dropped
        }
        return cls(
            source=columns,
            arrow_types=arrow_types,
            primary_key=keys,
            _by_name={column.name: column for column in columns},
            _hex_columns=hex_columns,
            _dropped_columns=dropped,
        )

    def matches(self, columns: Sequence[BinlogColumn], primary_key: Sequence[str] | str | None) -> bool:
        if self.primary_key != _key_list(primary_key):
            return False
        return self.source is columns or list(self.source) == list(columns)

    def normalize(
        self, values: Mapping[str, Any], none_sources: Mapping[str, str], time_zone: dt.tzinfo
    ) -> dict[str, Any]:
        """``none_sources`` tells why the library decoded a value as None. ``time_zone`` is the one the snapshot
        reads TIMESTAMP columns in, while the binlog stores them in UTC."""
        row: dict[str, Any] = {}
        for name, value in values.items():
            if name in self._dropped_columns:
                continue
            column = self._by_name.get(name)
            if value is None and none_sources.get(name) == NONE_SOURCE.EMPTY_SET:
                value = ""
            elif value is None or column is None:
                pass
            elif name in self._hex_columns:
                value = _as_bytes(value).hex()
            elif column.type in _TIMESTAMP_TYPES and isinstance(value, dt.datetime):
                value = value.replace(tzinfo=dt.UTC).astimezone(time_zone).replace(tzinfo=None)
            elif pa.types.is_string(self.arrow_types[name]):
                value = _as_string(value, column)
            row[name] = value
        return row
