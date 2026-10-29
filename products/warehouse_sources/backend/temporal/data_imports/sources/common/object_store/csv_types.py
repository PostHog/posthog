import re
from collections.abc import Callable, Mapping
from typing import Any, Literal, cast, get_args
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pyarrow as pa
import pyarrow.compute as pc

from posthog.dataclasses import frozen

# The types a CSV column can be cast to. Anything else stays a string column.
CsvColumnKind = Literal["integer", "unsigned", "float", "decimal", "boolean", "date", "datetime"]
CSV_COLUMN_KINDS: frozenset[str] = frozenset(get_args(CsvColumnKind))

_WRAPPER = re.compile(r"^(?:Nullable|LowCardinality)\((?P<inner>.*)\)$")
_TIMEZONE_ARGUMENT = re.compile(r"'(?P<timezone>[^']+)'")
_DECIMAL_ARGUMENTS = re.compile(r"^\s*(?P<first>\d+)\s*(?:,\s*(?P<second>\d+)\s*)?$")
_CLICKHOUSE_KINDS: dict[str, CsvColumnKind] = {
    "Int8": "integer",
    "Int16": "integer",
    "Int32": "integer",
    "Int64": "integer",
    "UInt8": "integer",
    "UInt16": "integer",
    "UInt32": "integer",
    "UInt64": "unsigned",
    "Float32": "float",
    "Float64": "float",
    "Bool": "boolean",
    "Date": "date",
    "Date32": "date",
    "DateTime": "datetime",
    "DateTime64": "datetime",
}
# `Decimal32(S)` and its siblings fix the precision and take only the scale.
_DECIMAL_PRECISIONS: dict[str, int | None] = {
    "Decimal": None,
    "Decimal32": 9,
    "Decimal64": 18,
    "Decimal128": 38,
    "Decimal256": 76,
}
# Arrow's 128-bit decimal holds 38 digits, which is also the most a Delta table can store.
_MAX_DECIMAL_PRECISION = 38
# Numbers no Arrow integer or 38-digit decimal holds, so a CSV column of them can't keep its type.
_WIDE_INTEGERS = frozenset({"Int128", "Int256", "UInt128", "UInt256"})
# A Delta table has no unsigned integers, and an Int64 can't hold the top half of UInt64, so a
# UInt64 is stored as a 20-digit decimal, which holds every UInt64 and stays a number.
_UNSIGNED_STORAGE = pa.decimal128(20, 0)
_FIXED_ARROW_TYPES: dict[CsvColumnKind, pa.DataType] = {
    "integer": pa.int64(),
    "unsigned": _UNSIGNED_STORAGE,
    "float": pa.float64(),
    "boolean": pa.bool_(),
    "date": pa.date32(),
    "datetime": pa.timestamp("us", tz="UTC"),
}
# The spellings ClickHouse accepts for a Bool in text formats.
_TRUE_VALUES = ["true", "1", "yes", "y", "on", "t", "enable"]
_FALSE_VALUES = ["false", "0", "no", "n", "off", "f", "disable"]
_UTC = "UTC"
# A failed cast is split in halves until a slice is this small, and only then cast value by value.
_PER_VALUE_SLICE = 32
_CAST_ERRORS = (pa.ArrowInvalid, pa.ArrowNotImplementedError, OverflowError)


class UnsupportedCsvColumnError(ValueError):
    """A stored column type that a CSV import can't keep. The message names the column."""


@frozen
class CsvColumnType:
    name: str
    kind: CsvColumnKind
    precision: int | None = None
    scale: int | None = None
    # The zone ClickHouse read naive values of a `datetime` column in. None reads them as UTC.
    timezone: str | None = None

    @property
    def arrow_type(self) -> pa.DataType:
        if self.kind == "decimal":
            return pa.decimal128(self.precision or _MAX_DECIMAL_PRECISION, self.scale or 0)
        return _FIXED_ARROW_TYPES[self.kind]

    def to_metadata(self) -> str | dict[str, Any]:
        if self.kind == "decimal":
            return {"kind": self.kind, "precision": self.precision, "scale": self.scale}
        if self.kind == "datetime" and self.timezone is not None:
            return {"kind": self.kind, "timezone": self.timezone}
        return self.kind


@frozen
class CsvCastResult:
    table: pa.Table
    # Per column, how many non-empty values could not be read as the column's type and became null.
    nulled_values: dict[str, int]


@frozen
class _ClickHouseType:
    base: str
    arguments: str


def _unwrap(clickhouse_type: str) -> _ClickHouseType:
    """The base type name and its arguments, without `Nullable(...)` or `LowCardinality(...)`."""
    inner = clickhouse_type.strip()
    while (wrapped := _WRAPPER.match(inner)) is not None:
        inner = wrapped.group("inner").strip()
    base, _, arguments = inner.partition("(")
    return _ClickHouseType(base=base.strip(), arguments=arguments.removesuffix(")"))


def clickhouse_base_type(clickhouse_type: str) -> str:
    return _unwrap(clickhouse_type).base


def _datetime_timezone(name: str, arguments: str) -> str | None:
    match = _TIMEZONE_ARGUMENT.search(arguments)
    if match is None:
        return None
    timezone = match.group("timezone")
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise UnsupportedCsvColumnError(f"the column '{name}' has a time zone '{timezone}' PostHog can't read") from e
    return None if timezone == _UTC else timezone


def _decimal_type(name: str, base: str, arguments: str) -> CsvColumnType:
    match = _DECIMAL_ARGUMENTS.match(arguments)
    if match is None:
        raise UnsupportedCsvColumnError(f"the column '{name}' has a decimal type PostHog can't read")
    fixed_precision = _DECIMAL_PRECISIONS[base]
    if fixed_precision is None:
        precision, scale = int(match.group("first")), int(match.group("second") or 0)
    else:
        precision, scale = fixed_precision, int(match.group("first"))
    if precision > _MAX_DECIMAL_PRECISION:
        raise UnsupportedCsvColumnError(
            f"the column '{name}' is a decimal with more than {_MAX_DECIMAL_PRECISION} digits"
        )
    return CsvColumnType(name=name, kind="decimal", precision=precision, scale=scale)


def csv_column_type(name: str, clickhouse_type: str) -> CsvColumnType | None:
    """The cast for a stored ClickHouse type, or None when the column stays a string.

    Raises `UnsupportedCsvColumnError` for a number that neither a cast nor a string column keeps.
    """
    parsed = _unwrap(clickhouse_type)
    base, arguments = parsed.base, parsed.arguments
    if base in _WIDE_INTEGERS:
        raise UnsupportedCsvColumnError(f"the column '{name}' is a {base}, which PostHog can't store")
    if base in _DECIMAL_PRECISIONS:
        return _decimal_type(name, base, arguments)
    kind = _CLICKHOUSE_KINDS.get(base)
    if kind is None:
        return None
    if kind == "datetime":
        return CsvColumnType(name=name, kind=kind, timezone=_datetime_timezone(name, arguments))
    return CsvColumnType(name=name, kind=kind)


def stored_clickhouse_types(columns: Mapping[str, Any] | None) -> dict[str, str]:
    """The ClickHouse type of each stored column, in stored order.

    A column ClickHouse marked as invalid never read as its type, so it is left out.
    """
    types: dict[str, str] = {}
    for name, definition in (columns or {}).items():
        if isinstance(definition, str):
            types[name] = definition
        elif isinstance(definition, Mapping) and definition.get("valid") is not False:
            types[name] = str(definition.get("clickhouse") or "")
    return types


def csv_column_types_from_columns(columns: Mapping[str, Any] | None) -> tuple[CsvColumnType, ...]:
    """The casts for a warehouse table's stored columns, in their stored order."""
    column_types: list[CsvColumnType] = []
    for name, clickhouse_type in stored_clickhouse_types(columns).items():
        column_type = csv_column_type(name, clickhouse_type)
        if column_type is not None:
            column_types.append(column_type)
    return tuple(column_types)


def _column_type_from_metadata(name: str, raw: object) -> CsvColumnType | None:
    if isinstance(raw, str):
        return CsvColumnType(name=name, kind=cast(CsvColumnKind, raw)) if raw in CSV_COLUMN_KINDS else None
    if not isinstance(raw, Mapping) or raw.get("kind") not in CSV_COLUMN_KINDS:
        return None
    precision, scale, timezone = raw.get("precision"), raw.get("scale"), raw.get("timezone")
    return CsvColumnType(
        name=name,
        kind=cast(CsvColumnKind, raw["kind"]),
        precision=precision if isinstance(precision, int) else None,
        scale=scale if isinstance(scale, int) else None,
        timezone=timezone if isinstance(timezone, str) else None,
    )


def csv_column_types_from_metadata(raw: object) -> tuple[CsvColumnType, ...]:
    if not isinstance(raw, Mapping):
        return ()
    column_types = (_column_type_from_metadata(name, value) for name, value in raw.items() if isinstance(name, str))
    return tuple(column_type for column_type in column_types if column_type is not None)


def _cast_each(values: pa.Array, parse: Callable[[pa.Array], pa.Array], target: pa.DataType) -> pa.Array:
    parsed: list[Any] = []
    for value in values.to_pylist():
        if value is None:
            parsed.append(None)
            continue
        try:
            parsed.append(parse(pa.array([value], pa.string()))[0].as_py())
        except _CAST_ERRORS:
            parsed.append(None)
    return pa.array(parsed, target)


def _cast_isolating_failures(values: pa.Array, parse: Callable[[pa.Array], pa.Array], target: pa.DataType) -> pa.Array:
    """Cast a slice that failed as a whole by halves, so only small slices are cast value by value.

    The cost then grows with the number of bad values times the log of the slice length, not with
    the length of every slice that holds one bad value.
    """
    if len(values) <= _PER_VALUE_SLICE:
        return _cast_each(values, parse, target)
    middle = len(values) // 2
    halves: list[pa.Array] = []
    for half in (values.slice(0, middle), values.slice(middle)):
        try:
            halves.append(parse(half))
        except _CAST_ERRORS:
            halves.append(_cast_isolating_failures(half, parse, target))
    return pa.concat_arrays(halves)


def _without_plus_sign(values: pa.Array) -> pa.Array:
    # Arrow refuses an explicit plus sign, which ClickHouse reads as part of the number.
    return cast(pa.Array, pc.replace_substring_regex(values, pattern=r"^\+", replacement=""))


def _parse_number(target: pa.DataType) -> Callable[[pa.Array], pa.Array]:
    return lambda values: pc.cast(_without_plus_sign(values), target)


def _parse_decimal(target: pa.DataType, scale: int) -> Callable[[pa.Array], pa.Array]:
    # ClickHouse drops the fractional digits a decimal's scale can't hold, rather than refusing the value.
    excess_digits = rf"^([+-]?\d*\.\d{{{scale}}})\d+$" if scale else r"^([+-]?\d+)\.\d*$"

    def parse(values: pa.Array) -> pa.Array:
        truncated = cast(
            pa.Array, pc.replace_substring_regex(_without_plus_sign(values), pattern=excess_digits, replacement=r"\1")
        )
        return pc.cast(truncated, target)

    return parse


def _parse_unsigned(values: pa.Array) -> pa.Array:
    # Read as UInt64 first, so a negative or too large value fails like it does in ClickHouse.
    return pc.cast(pc.cast(_without_plus_sign(values), pa.uint64()), _UNSIGNED_STORAGE)


def _parse_boolean(values: pa.Array) -> pa.Array:
    lowered = pc.utf8_lower(values)
    is_true = pc.is_in(lowered, value_set=pa.array(_TRUE_VALUES))
    is_false = pc.is_in(lowered, value_set=pa.array(_FALSE_VALUES))
    if not pc.all(pc.or_(pc.or_(is_true, is_false), pc.is_null(values))).as_py():
        raise pa.ArrowInvalid("not a boolean")
    return pc.if_else(pc.is_null(values), pa.scalar(None, pa.bool_()), is_true)


def _parse_timestamp(values: pa.Array, tz: str | None) -> pa.Array:
    """Parse text into a microsecond timestamp, truncating finer fractions of a second.

    A `DateTime64(9)` column, the type ClickHouse infers for a timestamp, can hold nanoseconds,
    which Arrow refuses to read as microseconds. Those values are read as nanoseconds first and
    then truncated to the microseconds a Delta table stores.
    """
    micros = pa.timestamp("us") if tz is None else pa.timestamp("us", tz=tz)
    nanos = pa.timestamp("ns") if tz is None else pa.timestamp("ns", tz=tz)
    try:
        return pc.cast(values, micros)
    except pa.ArrowInvalid:
        return pc.cast(pc.cast(values, nanos), micros, safe=False)


def _parse_datetime(timezone: str | None) -> Callable[[pa.Array], pa.Array]:
    target = _FIXED_ARROW_TYPES["datetime"]

    def parse(values: pa.Array) -> pa.Array:
        # ClickHouse reads a value without an offset in the column's time zone, or in UTC.
        try:
            naive = _parse_timestamp(values, None)
        except pa.ArrowInvalid:
            return _parse_timestamp(values, _UTC)
        if timezone is None:
            return pc.cast(naive, target)
        # A local time that a clock change skips or repeats takes the earlier instant.
        localized = pc.assume_timezone(
            cast(Any, naive), timezone=timezone, ambiguous="earliest", nonexistent="earliest"
        )
        return pc.cast(localized, target)

    return parse


def _parser(column_type: CsvColumnType) -> Callable[[pa.Array], pa.Array]:
    if column_type.kind == "boolean":
        return _parse_boolean
    if column_type.kind == "datetime":
        return _parse_datetime(column_type.timezone)
    if column_type.kind == "unsigned":
        return _parse_unsigned
    if column_type.kind == "decimal":
        return _parse_decimal(column_type.arrow_type, column_type.scale or 0)
    return _parse_number(column_type.arrow_type)


def cast_csv_columns(table: pa.Table, column_types: tuple[CsvColumnType, ...]) -> CsvCastResult:
    """Cast the string columns of a CSV batch to the stored types.

    A value that can't be read as its column's type becomes null rather than failing the file,
    and the caller reports how many values that happened to. The batch is cast as a whole first,
    so only the slices that hold such a value pay for a slower pass.
    """
    nulled: dict[str, int] = {}
    for column_type in column_types:
        if column_type.name not in table.column_names:
            continue
        index = table.schema.get_field_index(column_type.name)
        values = pc.utf8_trim_whitespace(table.column(index).combine_chunks())
        # A quoted empty field is an empty string, which no typed column can hold.
        values = pc.if_else(pc.equal(values, pa.scalar("", pa.string())), pa.scalar(None, pa.string()), values)
        target = column_type.arrow_type
        parse = _parser(column_type)
        try:
            cast_values = parse(values)
        except _CAST_ERRORS:
            cast_values = _cast_isolating_failures(values, parse, target)
            failed = cast_values.null_count - values.null_count
            if failed:
                nulled[column_type.name] = failed
        table = table.set_column(index, pa.field(column_type.name, target), cast_values)
    return CsvCastResult(table=table, nulled_values=nulled)
