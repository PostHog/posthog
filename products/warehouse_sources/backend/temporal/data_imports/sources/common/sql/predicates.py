"""Schema-level row-filter predicates for SQL sources.

A row filter is a `{column, operator, value}` triple ANDed onto a source query's
`WHERE` clause so a sync only pulls matching rows. This is the driver-free safety
boundary: it validates a filter against the schema's columns and coerces the value.

Three rails make SQL injection impossible by construction:

1. Column must exist in the schema's `schema_metadata`, and is quoted via `IdentifierQuoter`.
2. Operator is looked up from `_CANONICAL_OPERATORS`, never passed through from input.
3. Value is type-checked against the column's `ColumnTypeCategory` and always leaves as
   a bound parameter — the render helpers emit placeholders only.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any, TypedDict

from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.identifiers import IdentifierQuoter
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.metadata import (
    extract_available_column_names,
)


class RowFilterValidationError(ValueError):
    """Raised when a row filter fails validation (bad column, operator, or value type)."""


class ColumnTypeCategory(enum.Enum):
    """Coarse type category a column's `data_type` maps onto. `UNKNOWN` is a hard
    failure — we won't filter on a column whose value we can't type-check."""

    INTEGER = "integer"
    NUMERIC = "numeric"
    STRING = "string"
    BOOLEAN = "boolean"
    DATE = "date"
    TIMESTAMP = "timestamp"
    UNKNOWN = "unknown"


class RowFilter(TypedDict):
    """A row filter as it is persisted on the schema (raw JSON shape)."""

    column: str
    operator: str
    value: Any


@dataclass(frozen=True)
class ValidatedRowFilter:
    """A row filter after validation: canonical operator + coerced, typed value."""

    column: str
    operator: str
    value: Any
    category: ColumnTypeCategory


# The only operators that may reach SQL; input aliases normalize to these.
_SCALAR_OPERATORS = frozenset({">", ">=", "<", "<=", "=", "!="})
# Take a list of values, emitted as `(%s, %s, ...)`. Case-insensitive on input.
_MULTI_VALUE_OPERATORS = frozenset({"IN", "NOT IN"})
_CANONICAL_OPERATORS = _SCALAR_OPERATORS | _MULTI_VALUE_OPERATORS
_OPERATOR_ALIASES = {"==": "=", "<>": "!="}

MAX_ROW_FILTERS = 20
# Bound the number of parameters a single IN / NOT IN filter can emit.
MAX_IN_VALUES = 1000


def is_multi_value_operator(operator: str) -> bool:
    """True for `IN` / `NOT IN` — operators whose value is a list, not a scalar."""
    return operator in _MULTI_VALUE_OPERATORS


def normalize_operator(operator: Any) -> str:
    """Return the canonical operator for `operator`, or raise.

    Accepts the six scalar operators (plus `==`/`<>` aliases) and `IN`/`NOT IN`
    (case-insensitive). The result is always a member of `_CANONICAL_OPERATORS`,
    so callers can interpolate it directly.
    """
    if not isinstance(operator, str):
        raise RowFilterValidationError(f"Operator must be a string, got {type(operator).__name__}")
    stripped = operator.strip()
    # `IN` / `NOT IN`: case-insensitive, collapse runs of internal whitespace.
    collapsed = " ".join(stripped.upper().split())
    if collapsed in _MULTI_VALUE_OPERATORS:
        return collapsed
    candidate = _OPERATOR_ALIASES.get(stripped, stripped)
    if candidate in _SCALAR_OPERATORS:
        return candidate
    allowed = ", ".join([*sorted(_SCALAR_OPERATORS), *sorted(_MULTI_VALUE_OPERATORS)])
    raise RowFilterValidationError(f"Unsupported operator {operator!r}. Allowed operators: {allowed}")


def _strip_nullable_wrappers(data_type: str) -> str:
    """Unwrap ClickHouse `Nullable(...)` / `LowCardinality(...)` wrappers."""
    current = data_type.strip()
    while True:
        if current.startswith("Nullable(") and current.endswith(")"):
            current = current[len("Nullable(") : -1].strip()
        elif current.startswith("LowCardinality(") and current.endswith(")"):
            current = current[len("LowCardinality(") : -1].strip()
        else:
            return current


def _strip_type_params(data_type: str) -> str:
    """Drop trailing parameters, e.g. `varchar(255)` -> `varchar`, `numeric(10,2)` -> `numeric`."""
    paren = data_type.find("(")
    base = data_type if paren == -1 else data_type[:paren]
    return base.strip()


# Type vocabularies harvested from every SQL source's incremental-field classifier
# (postgres, mysql, mssql, snowflake, bigquery, redshift, clickhouse), widened to
# cover the non-incremental types a user may legitimately filter on.
_INTEGER_TYPES = {
    "int",
    "int2",
    "int4",
    "int8",
    "int16",
    "int32",
    "int64",
    "int128",
    "int256",
    "integer",
    "smallint",
    "mediumint",
    "bigint",
    "tinyint",
    "byteint",
    "serial",
    "smallserial",
    "bigserial",
    "uint8",
    "uint16",
    "uint32",
    "uint64",
    "uint128",
    "uint256",
}
_NUMERIC_TYPES = {
    "numeric",
    "decimal",
    "real",
    "double",
    "double precision",
    "float",
    "float4",
    "float8",
    "float32",
    "float64",
    "number",
    "money",
    "smallmoney",
    "bignumeric",
    "dec",
    "fixed",
}
_STRING_TYPES = {
    "char",
    "character",
    "character varying",
    "varchar",
    "varchar2",
    "nchar",
    "nvarchar",
    "nvarchar2",
    "text",
    "tinytext",
    "mediumtext",
    "longtext",
    "ntext",
    "string",
    "fixedstring",
    "clob",
    "nclob",
    "uuid",
    "uniqueidentifier",
    "name",
    "citext",
    "enum",
    # json / jsonb excluded: `jsonb <op> $text_param` fails at sync time without a cast, so we
    # treat them as UNKNOWN (unfilterable) rather than pass validation and break the sync.
}
_BOOLEAN_TYPES = {"bool", "boolean", "bit"}
_DATE_TYPES = {"date", "date32"}
_TIMESTAMP_TYPES = {
    "timestamp",
    "timestamptz",
    "timestamp with time zone",
    "timestamp without time zone",
    "datetime",
    "datetime2",
    "datetime64",
    "smalldatetime",
    "datetimeoffset",
}


def classify_column_type(data_type: Any) -> ColumnTypeCategory:
    """Map a driver-native `data_type` onto a `ColumnTypeCategory`, or `UNKNOWN`.

    Case-insensitive, after unwrapping `Nullable(...)` and dropping length/precision
    params. Prefix matches cover parameterized timestamp/datetime spellings.
    """
    if not isinstance(data_type, str) or not data_type.strip():
        return ColumnTypeCategory.UNKNOWN

    inner = _strip_nullable_wrappers(data_type)
    base = _strip_type_params(inner).lower()

    if base in _INTEGER_TYPES:
        return ColumnTypeCategory.INTEGER
    if base in _NUMERIC_TYPES:
        return ColumnTypeCategory.NUMERIC
    if base in _BOOLEAN_TYPES:
        return ColumnTypeCategory.BOOLEAN
    if base in _DATE_TYPES:
        return ColumnTypeCategory.DATE
    if base in _STRING_TYPES:
        return ColumnTypeCategory.STRING
    if base in _TIMESTAMP_TYPES or base.startswith("timestamp") or base.startswith("datetime"):
        return ColumnTypeCategory.TIMESTAMP
    return ColumnTypeCategory.UNKNOWN


def _coerce_integer(value: Any) -> int:
    if isinstance(value, bool):
        raise RowFilterValidationError("Expected an integer value, got a boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        raise RowFilterValidationError(f"Expected an integer value, got non-integral {value!r}")
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            raise RowFilterValidationError(f"Expected an integer value, got {value!r}")
    raise RowFilterValidationError(f"Expected an integer value, got {type(value).__name__}")


def _coerce_numeric(value: Any) -> int | float | Decimal:
    if isinstance(value, bool):
        raise RowFilterValidationError("Expected a numeric value, got a boolean")
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except InvalidOperation:
            raise RowFilterValidationError(f"Expected a numeric value, got {value!r}")
    raise RowFilterValidationError(f"Expected a numeric value, got {type(value).__name__}")


def _coerce_string(value: Any) -> str:
    if isinstance(value, str):
        return value
    raise RowFilterValidationError(f"Expected a string value, got {type(value).__name__}")


def _coerce_boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    # Accept 0/1 — a direct API caller may send these for a boolean column.
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    raise RowFilterValidationError(f"Expected a boolean value (true/false), got {value!r}")


def _coerce_date(value: Any) -> date:
    if not isinstance(value, str):
        raise RowFilterValidationError(f"Expected an ISO date string (YYYY-MM-DD), got {type(value).__name__}")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise RowFilterValidationError(f"Expected an ISO date string (YYYY-MM-DD), got {value!r}")


def _coerce_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise RowFilterValidationError(f"Expected an ISO datetime string, got {type(value).__name__}")
    raw = value.strip()
    # Accept a trailing "Z" (UTC) which older `fromisoformat` rejects.
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        # A plain date is a valid timestamp boundary (midnight).
        try:
            return datetime.combine(date.fromisoformat(raw), time())
        except ValueError:
            raise RowFilterValidationError(f"Expected an ISO datetime string, got {value!r}")


_COERCERS = {
    ColumnTypeCategory.INTEGER: _coerce_integer,
    ColumnTypeCategory.NUMERIC: _coerce_numeric,
    ColumnTypeCategory.STRING: _coerce_string,
    ColumnTypeCategory.BOOLEAN: _coerce_boolean,
    ColumnTypeCategory.DATE: _coerce_date,
    ColumnTypeCategory.TIMESTAMP: _coerce_timestamp,
}


def _split_top_level_commas(raw: str) -> list[str]:
    """Split on commas that are not inside single quotes; quote chars stay in each piece."""
    pieces: list[str] = []
    buf: list[str] = []
    in_quote = False
    i = 0
    n = len(raw)
    while i < n:
        ch = raw[i]
        if ch == "'":
            buf.append(ch)
            if in_quote and i + 1 < n and raw[i + 1] == "'":  # escaped '' -> keep both
                buf.append("'")
                i += 2
                continue
            in_quote = not in_quote
        elif ch == "," and not in_quote:
            pieces.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    if in_quote:
        raise RowFilterValidationError("Unterminated quote in IN list")
    pieces.append("".join(buf))
    return pieces


def _split_in_list(raw: str) -> list[str]:
    """Split a comma-separated IN list into trimmed element strings.

    A single-quoted element keeps its contents verbatim (may hold commas/spaces),
    with `''` read as an escaped quote. Blank input yields an empty list.
    """
    if not raw.strip():
        return []
    elements: list[str] = []
    for piece in _split_top_level_commas(raw):
        token = piece.strip()
        if len(token) >= 2 and token.startswith("'") and token.endswith("'"):
            elements.append(token[1:-1].replace("''", "'"))
        else:
            elements.append(token)
    return elements


def _coerce_in_values(value: Any, category: ColumnTypeCategory) -> list[Any]:
    """Parse and coerce an `IN` / `NOT IN` value into a typed list.

    Accepts a comma-separated string or an already-structured list. Each element is
    coerced with the same per-type rules as a scalar. Raises on an empty list, a blank
    element, too many values, or a coercion failure.
    """
    coercer = _COERCERS[category]
    if isinstance(value, list):
        elements: list[Any] = value
    elif isinstance(value, str):
        elements = _split_in_list(value)
    else:
        raise RowFilterValidationError(
            f"IN operator expects a comma-separated string or a list, got {type(value).__name__}"
        )

    if not elements:
        raise RowFilterValidationError("IN operator requires at least one value")
    if len(elements) > MAX_IN_VALUES:
        raise RowFilterValidationError(f"Too many values for IN (max {MAX_IN_VALUES})")

    coerced: list[Any] = []
    for element in elements:
        if isinstance(element, str) and element == "":
            raise RowFilterValidationError("IN list has an empty value")
        coerced.append(coercer(element))
    return coerced


def _column_types(schema_metadata: dict[str, Any] | None) -> dict[str, str]:
    """Map column name -> native `data_type` from a `schema_metadata` row."""
    if not isinstance(schema_metadata, dict):
        return {}
    columns = schema_metadata.get("columns")
    if not isinstance(columns, list):
        return {}
    result: dict[str, str] = {}
    for column in columns:
        if (
            isinstance(column, dict)
            and isinstance(column.get("name"), str)
            and isinstance(column.get("data_type"), str)
        ):
            result[column["name"]] = column["data_type"]
    return result


def validate_and_coerce_row_filters(
    row_filters: Any,
    schema_metadata: dict[str, Any] | None,
) -> list[ValidatedRowFilter]:
    """Validate raw row filters against a schema's columns and coerce their values.

    Returns an empty list for `None`/empty input. Raises `RowFilterValidationError`
    on a malformed structure, unknown column, disallowed operator, unclassifiable
    type, or a value that doesn't match the column's type.
    """
    if row_filters is None:
        return []
    if not isinstance(row_filters, list):
        raise RowFilterValidationError("row_filters must be a list")
    if len(row_filters) > MAX_ROW_FILTERS:
        raise RowFilterValidationError(f"Too many row filters (max {MAX_ROW_FILTERS})")

    available_columns = extract_available_column_names(schema_metadata)
    column_types = _column_types(schema_metadata)

    validated: list[ValidatedRowFilter] = []
    for index, row_filter in enumerate(row_filters):
        if not isinstance(row_filter, dict):
            raise RowFilterValidationError(f"Row filter at index {index} must be an object")

        column = row_filter.get("column")
        if not isinstance(column, str) or not column:
            raise RowFilterValidationError(f"Row filter at index {index} is missing a column")
        if available_columns and column not in available_columns:
            raise RowFilterValidationError(f"Unknown column {column!r} for this schema")

        operator = normalize_operator(row_filter.get("operator"))

        data_type = column_types.get(column)
        category = classify_column_type(data_type)
        if category is ColumnTypeCategory.UNKNOWN:
            raise RowFilterValidationError(
                f"Cannot filter on column {column!r}: its type {data_type!r} is not supported for filtering"
            )

        if "value" not in row_filter:
            raise RowFilterValidationError(f"Row filter on column {column!r} is missing a value")
        if is_multi_value_operator(operator):
            # `value` becomes a typed list; render helpers expand it to N placeholders.
            coerced: Any = _coerce_in_values(row_filter["value"], category)
        else:
            coerced = _COERCERS[category](row_filter["value"])

        validated.append(ValidatedRowFilter(column=column, operator=operator, value=coerced, category=category))

    return validated


def render_named_conditions(
    filters: list[ValidatedRowFilter],
    quoter: IdentifierQuoter,
    *,
    prefix: str = "row_filter",
) -> tuple[list[str], dict[str, Any]]:
    """Render filters as pyformat-named conditions (`%(name)s`) + a params dict.

    Used by MySQL/MSSQL. Columns are quoted via `quoter`; values leave only as params.
    """
    conditions: list[str] = []
    params: dict[str, Any] = {}
    for index, row_filter in enumerate(filters):
        quoted = quoter.quote(row_filter.column)
        if is_multi_value_operator(row_filter.operator):
            placeholders = []
            for position, element in enumerate(row_filter.value):
                name = f"{prefix}_{index}_{position}"
                params[name] = element
                placeholders.append(f"%({name})s")
            conditions.append(f"{quoted} {row_filter.operator} ({', '.join(placeholders)})")
        else:
            name = f"{prefix}_{index}"
            params[name] = row_filter.value
            conditions.append(f"{quoted} {row_filter.operator} %({name})s")
    return conditions, params


def render_positional_conditions(
    filters: list[ValidatedRowFilter],
    quoter: IdentifierQuoter,
) -> tuple[list[str], list[Any]]:
    """Render filters as positional conditions (`%s`) + an ordered values list.

    Used by Snowflake; the caller must append these values after any earlier
    positional params (e.g. the incremental value).
    """
    conditions: list[str] = []
    values: list[Any] = []
    for row_filter in filters:
        quoted = quoter.quote(row_filter.column)
        if is_multi_value_operator(row_filter.operator):
            placeholders = ", ".join(["%s"] * len(row_filter.value))
            conditions.append(f"{quoted} {row_filter.operator} ({placeholders})")
            values.extend(row_filter.value)
        else:
            conditions.append(f"{quoted} {row_filter.operator} %s")
            values.append(row_filter.value)
    return conditions, values
