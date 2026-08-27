from __future__ import annotations

import json
import math
import uuid
import decimal
import datetime
from collections.abc import Callable, Iterable, Iterator, Sequence
from functools import _make_key, wraps
from ipaddress import IPv4Address, IPv6Address
from typing import TYPE_CHECKING, Any, Literal, Optional, cast

import numpy as np
import orjson
import pyarrow as pa
import deltalake as deltalake
import pyarrow.compute as pc
from arro3.core.types import ArrowSchemaExportable
from circular_dict import CircularDict
from dateutil import parser
from dlt.common.libs.deltalake import ensure_delta_compatible_arrow_schema
from structlog.types import FilteringBoundLogger

from posthog.temporal.common.errors import NonReportableError

from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.consts import PARTITION_KEY
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

if TYPE_CHECKING:
    pass

DLT_TO_PA_TYPE_MAP: dict[
    Literal["text", "bigint", "bool", "timestamp", "json", "double", "date", "time", "decimal"], pa.DataType
] = {
    "text": pa.string(),
    "bigint": pa.int64(),
    "bool": pa.bool_(),
    "timestamp": pa.timestamp("us"),
    "json": pa.string(),
    "double": pa.float64(),
    "date": pa.date64(),
    "time": pa.timestamp("us"),
    "decimal": pa.float64(),
}

DEFAULT_NUMERIC_PRECISION = 38  # Delta Lake maximum precision
DEFAULT_NUMERIC_SCALE = 18  # Good default scale for decimal128, 20 int digits plus 18 decimal cases
MAX_NUMERIC_SCALE = 32  # Maximum scale for Delta Lake

# pyarrow infers `int64` for Python `int` columns; values outside this range overflow with
# "OverflowError: Python int too large to convert to C long" (Python ints are unbounded).
INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1

type SupportedDltDataType = Literal["text", "bigint", "bool", "timestamp", "json", "double", "date", "time", "decimal"]
type DecimalInput = decimal.Decimal | float | str | tuple[int, Sequence[int], int]


class BillingLimitsWillBeReachedException(NonReportableError):
    """The sync was intentionally halted because the account will cross its Data Warehouse billing
    limit. Expected control flow, not a defect: the workflow marks the job BILLING_LIMIT_TOO_LOW,
    and subclassing NonReportableError keeps it out of error tracking."""


class DuplicatePrimaryKeysException(Exception):
    pass


# Matched as a substring by the shared non-retryable classification (`Any_Source_Errors`) and by the
# v3 load consumer, so both keep recognizing the condition — keep the wording in step with them.
MISSING_PRIMARY_KEYS_ERROR = "Primary key required for incremental syncs"


class MissingPrimaryKeysException(Exception):
    """An incremental table has no primary key to merge on, so it can't be merged into the
    already-written Delta table. Permanent until the user picks a key or switches the sync type."""

    def __init__(self, message: str = MISSING_PRIMARY_KEYS_ERROR) -> None:
        super().__init__(message)


class QueryTimeoutException(Exception):
    pass


class TemporaryFileSizeExceedsLimitException(Exception):
    pass


class SchemaColumnTypeChangedException(Exception):
    """Raised when an incoming column can't be cast into the existing (narrower) Delta column type.

    The usual cause is the source column's type being widened upstream (e.g. Postgres
    `integer` → `bigint`) after the Delta table was already created with the narrower type.
    delta-rs cannot widen an existing column in place, so retrying is futile — the table must
    be reset and fully re-synced to adopt the new type.

    ``column_name`` / ``stored_type`` / ``incoming_type`` are populated only where a clean
    stored-to-incoming type pair exists (the cast failure in ``evolve_pyarrow_schema``). The
    value-driven raises (decimal overflow, nullability drift) leave them ``None``, which keeps
    those cases out of automatic widening recovery by construction (see
    ``auto_widen_resync.maybe_schedule_auto_widen_resync``).
    """

    def __init__(
        self,
        message: str,
        *,
        column_name: str | None = None,
        stored_type: pa.DataType | None = None,
        incoming_type: pa.DataType | None = None,
    ) -> None:
        super().__init__(message)
        self.column_name = column_name
        self.stored_type = stored_type
        self.incoming_type = incoming_type


def is_safe_numeric_widening(stored_type: pa.DataType, incoming_type: pa.DataType) -> bool:
    """Whether a stored-to-incoming column type change is mechanically recoverable by a reset
    and full re-sync, with no human judgement needed.

    "Safe" means both sides are plain numeric types, so a re-sync deterministically adopts the
    source's new type, which is the exact outcome the manual "Reset" remedy produces. That deliberately
    includes transitions that aren't strict range widenings (int8 → uint8) and int64 → float64
    (lossy above 2^53): the source already emits values of the new type either way, so an
    automatic reset can never lose anything the manual reset would have kept. Transitions
    involving non-numeric types (string, bool, decimal, temporal, nested) need human judgement
    and stay manual.
    """
    return (
        (pa.types.is_integer(stored_type) or pa.types.is_floating(stored_type))
        and (pa.types.is_integer(incoming_type) or pa.types.is_floating(incoming_type))
        and stored_type != incoming_type
    )


def normalize_column_name(column_name: str) -> str:
    return NamingConvention.normalize_identifier(column_name)


def pyarrow_schema_from_arrow_exportable(schema: ArrowSchemaExportable) -> pa.Schema:
    # PyArrow's stubs don't model Arrow C Data Interface inputs here.
    return pa.schema(cast(Any, schema))


def safe_parse_datetime(date_str: object | None) -> None | pa.TimestampScalar | datetime.datetime:
    try:
        if date_str is None:
            return None

        if isinstance(date_str, pa.StringScalar):
            scalar = cast(str | None, date_str.as_py())

            if scalar is None:
                return None

            return parser.parse(scalar)

        if isinstance(date_str, pa.TimestampScalar):
            return date_str

        if isinstance(date_str, str | bytes):
            return parser.parse(date_str)

        return None
    except (ValueError, OverflowError, TypeError):
        return None


def _handle_null_columns_with_definitions(table: pa.Table, source: SourceResponse) -> pa.Table:
    column_hints = source.column_hints

    if column_hints is None:
        return table

    for field_name, data_type in column_hints.items():
        if data_type is None:
            continue

        normalized_field_name = normalize_column_name(field_name)
        # If the table doesn't have all fields, then add a field with all Nulls and the correct field type
        if normalized_field_name not in table.schema.names:
            new_column = pa.array(
                [None] * table.num_rows,
                type=DLT_TO_PA_TYPE_MAP[cast(SupportedDltDataType, data_type)],
            )
            table = table.append_column(normalized_field_name, new_column)

    return table


def get_default_value_for_pyarrow_type(arrow_type: pa.DataType) -> Any:
    if pa.types.is_integer(arrow_type):
        return 0
    elif pa.types.is_floating(arrow_type):
        return 0.0
    elif pa.types.is_boolean(arrow_type):
        return False
    elif pa.types.is_string(arrow_type) or pa.types.is_large_string(arrow_type):
        return ""
    elif pa.types.is_binary(arrow_type) or pa.types.is_large_binary(arrow_type):
        return b""
    elif pa.types.is_timestamp(arrow_type):
        return pa.scalar(0, type=arrow_type).as_py()
    elif pa.types.is_date(arrow_type):
        return pa.scalar(0, type=arrow_type).as_py()
    elif pa.types.is_time(arrow_type):
        return pa.scalar(0, type=arrow_type).as_py()
    elif pa.types.is_list(arrow_type):
        return []
    elif pa.types.is_struct(arrow_type):
        return {}
    elif pa.types.is_dictionary(arrow_type):
        return {}
    elif pa.types.is_decimal(arrow_type):
        return decimal.Decimal(0)
    elif pa.types.is_duration(arrow_type):
        return 0
    elif pa.types.is_null(arrow_type):
        return None
    else:
        raise ValueError(f"Unsupported PyArrow type: {arrow_type}")


def _time_to_seconds(value: datetime.time) -> float:
    return value.hour * 3600 + value.minute * 60 + value.second + value.microsecond / 1_000_000


def evolve_pyarrow_schema(
    incoming_table: pa.Table,
    delta_schema: deltalake.Schema | None,
    merge_key_columns: Sequence[str] | None = None,
) -> pa.Table:
    # First pass: normalize types that Delta write path does not handle well.
    for column_name in incoming_table.column_names:
        incoming_column = incoming_table.column(column_name)
        incoming_field = incoming_table.field(column_name)

        # Convert nested values to JSON strings for stable schema writes.
        if pa.types.is_struct(incoming_column.type) or pa.types.is_list(incoming_column.type):
            nested_values = cast(list[object | None], incoming_column.to_pylist())
            json_column = pa.array([_json_dumps(value) if value is not None else None for value in nested_values])
            incoming_table = incoming_table.set_column(
                incoming_table.schema.get_field_index(column_name), column_name, json_column
            )
            incoming_column = incoming_table.column(column_name)
        # Convert duration to numeric seconds.
        elif pa.types.is_duration(incoming_column.type):
            duration_values = cast(list[datetime.timedelta | None], incoming_column.to_pylist())
            seconds_column = pa.array(
                [value.total_seconds() if value is not None else None for value in duration_values]
            )
            incoming_table = incoming_table.set_column(
                incoming_table.schema.get_field_index(column_name), column_name, seconds_column
            )
            incoming_column = incoming_table.column(column_name)
        # Convert time-of-day to numeric seconds. SQL sources map a TIME column to time64, but a
        # batch whose TIME values arrive as Python timedelta infers as duration and lands as float
        # seconds above — so the same column oscillates between time64 and double across batches
        # (a batch with values vs an all-null batch), and time64 has no cast to double. Collapsing
        # time to seconds here keeps the stored Delta type stable across both shapes.
        elif pa.types.is_time(incoming_column.type):
            time_values = cast(list[datetime.time | None], incoming_column.to_pylist())
            seconds_column = pa.array(
                [_time_to_seconds(value) if value is not None else None for value in time_values],
                type=pa.float64(),
            )
            incoming_table = incoming_table.set_column(
                incoming_table.schema.get_field_index(column_name), column_name, seconds_column
            )
            incoming_column = incoming_table.column(column_name)

        # Normalize timestamps to microseconds and no timezone. Delta only supports
        # microsecond precision, so any other unit (not just "ns") must be caught here —
        # e.g. the Snowflake connector's zero-row `_create_empty_table` path ignores
        # `force_microsecond_precision` and yields second-precision columns.
        if pa.types.is_timestamp(incoming_field.type) and (
            incoming_field.type.unit != "us" or incoming_field.type.tz is not None
        ):
            microsecond_timestamps = pc.cast(incoming_column, pa.timestamp("us"), safe=False).combine_chunks()
            incoming_table = incoming_table.set_column(
                incoming_table.schema.get_field_index(column_name), column_name, microsecond_timestamps
            )

    if not delta_schema:
        return incoming_table.cast(ensure_delta_compatible_arrow_schema(incoming_table.schema))

    # Second pass: align with existing Delta table schema.
    delta_arrow_schema = pyarrow_schema_from_arrow_exportable(delta_schema)
    merge_keys = {_fold_column_name_for_match(name) for name in merge_key_columns or []}
    for delta_field in delta_arrow_schema:
        if delta_field.name not in incoming_table.schema.names:
            new_column_data = (
                pa.array([None] * incoming_table.num_rows, type=delta_field.type)
                if delta_field.nullable
                else pa.array(
                    [get_default_value_for_pyarrow_type(delta_field.type)] * incoming_table.num_rows,
                    type=delta_field.type,
                )
            )
            incoming_table = incoming_table.append_column(delta_field, new_column_data)

        incoming_column = incoming_table.column(delta_field.name)

        if (
            pa.types.is_decimal(delta_field.type)
            and pa.types.is_decimal(incoming_column.type)
            and incoming_column.type != delta_field.type
        ):
            delta_dec = cast(pa.Decimal128Type | pa.Decimal256Type, delta_field.type)
            incoming_dec = cast(pa.Decimal128Type | pa.Decimal256Type, incoming_column.type)
            field_index = incoming_table.schema.get_field_index(delta_field.name)

            # Build candidate types in preference order: exact delta → minimal merged decimal128 → decimal256.
            candidates: list[pa.DataType] = []

            if delta_dec.scale == incoming_dec.scale and delta_dec.precision <= incoming_dec.precision:
                candidates.append(delta_field.type)

            delta_int = delta_dec.precision - delta_dec.scale
            incoming_int = incoming_dec.precision - incoming_dec.scale
            max_int = max(delta_int, incoming_int)
            if max_int <= 38:
                merged_scale = min(max(delta_dec.scale, incoming_dec.scale), 38 - max_int)
                candidates.append(pa.decimal128(max_int + merged_scale, merged_scale))

            candidates.append(pa.decimal256(76, incoming_dec.scale))

            for target in candidates:
                if target == incoming_column.type:
                    break
                try:
                    target_schema = incoming_table.schema.set(
                        field_index, incoming_table.schema.field(field_index).with_type(target)
                    )
                    incoming_table = incoming_table.cast(target_schema)
                    break
                except pa.ArrowInvalid:
                    continue

            incoming_column = incoming_table.column(delta_field.name)

        if delta_field.type != incoming_column.type and not (
            pa.types.is_decimal(delta_field.type) and pa.types.is_decimal(incoming_column.type)
        ):
            if isinstance(delta_field.type, pa.TimestampType):
                if (
                    isinstance(incoming_column.type, pa.TimestampType)
                    and delta_field.type.tz != incoming_column.type.tz
                ):
                    casted_column = incoming_column.cast(delta_field.type).combine_chunks()
                    incoming_table = incoming_table.set_column(
                        incoming_table.schema.get_field_index(delta_field.name), delta_field.name, casted_column
                    )
                else:
                    parsed_timestamps = pa.array(
                        [safe_parse_datetime(s) for s in incoming_column], type=delta_field.type
                    )
                    incoming_table = incoming_table.set_column(
                        incoming_table.schema.get_field_index(delta_field.name), delta_field.name, parsed_timestamps
                    )
            elif (
                _fold_column_name_for_match(delta_field.name) in merge_keys
                and (pa.types.is_binary(delta_field.type) or pa.types.is_large_binary(delta_field.type))
                and (pa.types.is_string(incoming_column.type) or pa.types.is_large_string(incoming_column.type))
            ):
                # A table written before `hex_encode_id_binary_columns` stores this key as raw
                # bytes while the batch now carries hex text. pyarrow casts string to binary
                # without complaint, which would store the hex text as bytes: the merge predicate
                # would then match no stored row and re-insert every incoming row. Fail instead,
                # so the table is reset and re-synced onto the hex representation.
                #
                # Only merge keys (primary keys and the partition-key source columns) take this
                # path. Every other column casts as before, so a source that legitimately turns a
                # non-key binary column into a string column keeps syncing.
                raise SchemaColumnTypeChangedException(
                    f"Source column type changed: merge key '{delta_field.name}' is stored as {delta_field.type} "
                    f"but now arrives as text ({incoming_column.type}). Reset and fully re-sync this table to "
                    f"adopt the new type.",
                    column_name=delta_field.name,
                    stored_type=delta_field.type,
                    incoming_type=incoming_column.type,
                )
            else:
                try:
                    casted_column = incoming_column.cast(delta_field.type).combine_chunks()
                except (pa.ArrowInvalid, pa.ArrowNotImplementedError) as e:
                    # Reaching this cast already means the incoming type differs from the stored
                    # Delta type (see the guard above) and the timestamp path didn't apply, so a
                    # failure here is a deterministic, unretryable incompatibility: the source
                    # column's type changed under a table created with a narrower type. Common
                    # shapes are an integer column widened upstream (Postgres `integer` → `bigint`),
                    # an integer-created column now receiving fractional values ("Float value 19.99
                    # was truncated converting to int64"), non-numeric text arriving for a numeric
                    # column ("Failed to parse string: '80-150' as a scalar of type int32"), a
                    # value that overflows the stored decimal precision, or a cast pyarrow has no
                    # kernel for at all (raised as ArrowNotImplementedError rather than
                    # ArrowInvalid). delta-rs cannot change a column's type in place, so
                    # retrying is futile — surface an actionable error telling the user to reset and
                    # fully re-sync. Lossless widening (e.g. a whole-valued float into an integer
                    # column) still casts fine and never reaches here.
                    raise SchemaColumnTypeChangedException(
                        f"Source column type changed: '{delta_field.name}' has values that no longer "
                        f"fit its stored type {delta_field.type} (incoming data is now "
                        f"{incoming_column.type}). Reset and fully re-sync this table to adopt the new type.",
                        column_name=delta_field.name,
                        stored_type=delta_field.type,
                        incoming_type=incoming_column.type,
                    ) from e

                incoming_table = incoming_table.set_column(
                    incoming_table.schema.get_field_index(delta_field.name),
                    delta_field.name,
                    casted_column,
                )

            incoming_column = incoming_table.column(delta_field.name)

        # Delta column is non-nullable: backfill nulls before write. Checked against the column's
        # actual null count, not its field's own `nullable` flag, because that flag is just metadata
        # and can say non-nullable while the batch still carries a real null (e.g. a batch scanned
        # from a table whose column is otherwise declared non-nullable), which would otherwise
        # skip the backfill and let the null reach the write.
        incoming_field = incoming_table.field(delta_field.name)
        if not delta_field.nullable and incoming_column.null_count > 0:
            filled_nulls_arr = incoming_column.fill_null(
                fill_value=get_default_value_for_pyarrow_type(incoming_field.type)
            )
            incoming_table = incoming_table.set_column(
                incoming_table.schema.get_field_index(delta_field.name),
                delta_field,
                filled_nulls_arr.combine_chunks(),
            )

    # Change types based on what deltalake tables support
    return incoming_table.cast(ensure_delta_compatible_arrow_schema(incoming_table.schema))


def _append_debug_column_to_pyarrows_table(table: pa.Table, load_id: int) -> pa.Table:
    debug_info = f'{{"load_id": {load_id}}}'

    column = pa.array([debug_info] * table.num_rows, type=pa.string())
    return table.append_column("_ph_debug", column)


def normalize_table_column_names(table: pa.Table) -> pa.Table:
    used_names = set()

    for column_name in table.column_names:
        normalized_column_name = normalize_column_name(column_name)
        temp_name = normalized_column_name

        if temp_name != column_name:
            while temp_name in used_names or temp_name in table.column_names:
                temp_name = "_" + temp_name

            table = table.set_column(
                table.schema.get_field_index(column_name),
                temp_name,
                table.column(column_name),
            )
            used_names.add(temp_name)

    return table


INTERNAL_COLUMN_NAMES = frozenset({"_ph_debug", PARTITION_KEY, "_dlt_id", "_dlt_load_id"})


def _fold_column_name_for_match(name: str) -> str:
    try:
        return NamingConvention.normalize_identifier(name)
    except ValueError:
        return name


def apply_enabled_columns_projection(
    table: pa.Table,
    enabled_columns: list[str] | None,
    primary_keys: list[str] | None,
    incremental_field: str | None,
    partition_keys: list[str] | None,
) -> tuple[pa.Table, list[str]]:
    """Drop table columns not selected in `enabled_columns`. Returns `(table, dropped_names)`.

    Delta-write-side counterpart of the SQL sources' SELECT projection, for sources that can't
    push the projection into the fetch. `None` means all columns sync. Primary keys, the active
    incremental field, partition-key source columns, and the pipeline's own internal columns
    (`INTERNAL_COLUMN_NAMES`) are always retained — matched by exact name, not prefix, so an
    upstream source can't smuggle a deselected column past the projection by naming it e.g.
    `_ph_secret` or `_dlt_secret`. Both sides are folded through the dlt naming convention: the table has already been
    through `normalize_table_column_names` while `enabled_columns`/primary keys arrive in the
    source namespace, so a raw comparison would drop every non-lowercase column. If the
    projection would drop every user-facing column, the table is returned unchanged (mirrors the
    empty-projection fallback in `filter_dwh_columns_by_enabled_columns`) — an empty table is
    never the intended result of a column selection.
    """
    if enabled_columns is None:
        return table, []

    retained = {_fold_column_name_for_match(name) for name in enabled_columns}
    for primary_key in primary_keys or []:
        retained.add(_fold_column_name_for_match(primary_key))
    if incremental_field:
        retained.add(_fold_column_name_for_match(incremental_field))
    for partition_key in partition_keys or []:
        retained.add(_fold_column_name_for_match(partition_key))

    kept_names = [
        name
        for name in table.column_names
        if name in INTERNAL_COLUMN_NAMES or _fold_column_name_for_match(name) in retained
    ]
    dropped_names = [name for name in table.column_names if name not in set(kept_names)]
    if not dropped_names:
        return table, []
    if all(name in INTERNAL_COLUMN_NAMES for name in kept_names):
        return table, []
    return table.select(kept_names), dropped_names


async def observe_and_project_table(
    table: pa.Table,
    enabled_columns: list[str] | None,
    primary_keys: list[str] | None,
    incremental_field: str | None,
    partition_keys: list[str] | None,
    observed_columns: dict[str, dict[str, Any]],
    logger: FilteringBoundLogger,
    log_message: str,
) -> pa.Table:
    """Shared observe-then-project step for `_uses_delta_write_column_selection` pipelines.

    Unions the batch's columns into `observed_columns` (for the column picker) before dropping
    non-enabled ones, so a pinned selection never hides a column from the picker. `log_message`
    is logged with the dropped column names appended, letting each pipeline keep its own wording.
    """
    for observed_column in observed_schema_metadata_columns(table.schema):
        observed_columns[observed_column["name"]] = observed_column

    table, dropped_names = apply_enabled_columns_projection(
        table, enabled_columns, primary_keys, incremental_field, partition_keys
    )
    if dropped_names:
        await logger.adebug(f"{log_message}: {dropped_names}")
    return table


def source_uses_delta_write_column_selection(source_type: str) -> bool:
    """True when the pipeline applies `enabled_columns` by dropping columns before the Delta
    write (and captures the observed columns into `schema_metadata`).

    False for:
    - SQL sources — they project `enabled_columns` into their SELECT and own
      `schema_metadata["columns"]` via schema introspection;
    - managed-schema sources (Stripe/Paddle/Zendesk) — column selection is disabled for them
      (their canonical HogQL schema needs the full physical column set), so the pipeline must
      never drop their columns even if a stale `enabled_columns` is still persisted.
    """
    # Imported lazily: the registry pulls in every source's (often heavy) dependencies on first use.
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import (
        SourceRegistry,  # noqa: PLC0415
    )
    from products.warehouse_sources.backend.types import ExternalDataSourceType  # noqa: PLC0415

    try:
        source = SourceRegistry.get_source(ExternalDataSourceType(source_type))
    except Exception:
        return False
    return not source.supports_column_selection and not source.has_managed_hogql_schema


def observed_schema_metadata_columns(schema: pa.Schema) -> list[dict[str, Any]]:
    """`schema_metadata["columns"]`-shaped entries from a pre-projection arrow schema.

    Captured before `apply_enabled_columns_projection` so the persisted catalog keeps listing
    columns the source returns even while they're being dropped — otherwise a pinned selection
    would make deselected (and newly-added upstream) columns invisible to the column picker.
    """
    return [
        {"name": field.name, "data_type": str(field.type), "is_nullable": field.nullable}
        for field in schema
        if field.name not in INTERNAL_COLUMN_NAMES
    ]


def merge_observed_columns_into_schema_metadata(config: dict[str, Any], observed_columns: list[dict[str, Any]]) -> None:
    """Union observed column entries into `sync_type_config["schema_metadata"]["columns"]` in place.

    Existing entries keep their position and are refreshed with the observed type/nullability;
    columns previously observed but absent from this run stay listed (union, not replace) so a
    projection or an upstream removal never shrinks the picker. Designed as a `mutate` callback
    for `update_sync_type_config_keys`.
    """
    metadata = config.get("schema_metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        config["schema_metadata"] = metadata
    columns = metadata.get("columns")
    if not isinstance(columns, list):
        columns = []
    metadata["columns"] = columns
    entries_by_name = {
        column.get("name"): column for column in columns if isinstance(column, dict) and column.get("name")
    }
    for observed in observed_columns:
        existing = entries_by_name.get(observed["name"])
        if existing is None:
            columns.append(observed)
        else:
            existing["data_type"] = observed["data_type"]
            existing["is_nullable"] = observed["is_nullable"]


BINARY_ID_COLUMN_NAMES = {"id", "uuid", "guid"}


def _is_id_like_column(column_name: str, primary_keys: Sequence[str] | None) -> bool:
    lowered = column_name.lower()
    if lowered in BINARY_ID_COLUMN_NAMES or lowered.endswith("_id"):
        return True
    return any(lowered == key.lower() for key in (primary_keys or []))


def _hex_arrays_or_report(
    value_chunks: Iterable[Sequence[bytes | None]],
    column_name: str,
    binary_reporter: Optional[BinaryColumnReporter],
    hex_type: pa.DataType,
) -> Optional[list[pa.Array]]:
    """Lowercase-hex strings for one binary column, or None when the values can't be converted.

    Takes the column one chunk at a time so the Python `bytes` and `str` objects of a whole
    column are never live at once — an Arrow-native source hands over batches far larger than
    the row path's, and this is the only step that leaves Arrow.

    Callers decide what None means: the row path drops the column, the Arrow path leaves it
    binary. Both report the same way.
    """
    try:
        hex_arrays: list[pa.Array] = [
            pa.array([None if value is None else value.hex() for value in chunk], type=hex_type)
            for chunk in value_chunks
        ]
    # pa.ArrowException also catches the 32-bit offset overflow of a chunk whose hex crosses
    # 2 GB, which is an ArrowCapacityError and so sits outside ValueError.
    except (AttributeError, TypeError, ValueError, pa.ArrowException) as e:
        if binary_reporter:
            binary_reporter.conversion_failed(column_name, e)
        return None

    if binary_reporter:
        binary_reporter.converted(column_name)
    return hex_arrays


class BinaryColumnReporter:
    """Logs each binary column's outcome once per instance lifetime (one sync), because
    `_process_batch` runs per batch and logging there directly would repeat the same line
    for every batch in the sync logs."""

    def __init__(self, logger: FilteringBoundLogger) -> None:
        self._logger = logger
        self._reported_columns: set[str] = set()

    def _once(self, column_name: str) -> bool:
        if column_name in self._reported_columns:
            return False
        self._reported_columns.add(column_name)
        return True

    def converted(self, column_name: str) -> None:
        if self._once(column_name):
            self._logger.info(f"Column '{column_name}' has a binary data type. Its values were synced as hex strings.")

    def dropped(self, column_name: str) -> None:
        if self._once(column_name):
            self._logger.warning(
                f"Column '{column_name}' was not synced because its binary data type is not supported."
            )

    def conversion_failed(self, column_name: str, error: Exception) -> None:
        if self._once(column_name):
            self._logger.warning(
                f"Column '{column_name}' was not synced because its binary values could not be converted to hex strings: {error}"
            )


def hex_encode_id_binary_columns(
    table: pa.Table,
    primary_keys: Optional[Sequence[str]] = None,
    binary_reporter: Optional[BinaryColumnReporter] = None,
) -> pa.Table:
    """Convert id-like binary columns of an Arrow-native batch to lowercase hex strings.

    Sources that hand the pipeline Arrow tables (BigQuery, Snowflake, Databricks, MotherDuck)
    never reach `_process_batch`, so their binary keys land in Delta as raw bytes, which cannot
    be read or joined in HogQL. Same name/primary-key gate as the row path.

    Non-key binary columns stay untouched: this path has always synced them, so dropping them
    the way the row path does would delete data these tables already carry.
    """
    for index, field in enumerate(table.schema):
        if not (pa.types.is_binary(field.type) or pa.types.is_large_binary(field.type)):
            continue
        if not _is_id_like_column(field.name, primary_keys):
            continue

        # Indexed, not by name: a batch carrying the same column name twice makes the name
        # lookup raise instead of converting.
        column = table.column(index)
        # Keep 64-bit offsets where the source column has them: hex doubles the byte length.
        hex_type = pa.large_string() if pa.types.is_large_binary(field.type) else pa.string()
        hex_arrays = _hex_arrays_or_report(
            (chunk.to_pylist() for chunk in column.chunks), field.name, binary_reporter, hex_type
        )
        if hex_arrays is None:
            continue

        table = table.set_column(index, field.with_type(hex_type), pa.chunked_array(hex_arrays, type=hex_type))

    return table


def _convert_uuid_to_string(row: dict) -> dict:
    return {key: str(value) if isinstance(value, uuid.UUID) else value for key, value in row.items()}


def _json_dumps(obj: Any) -> str:
    try:
        return orjson.dumps(obj).decode()
    except TypeError:
        try:
            return json.dumps(obj)
        except:
            return str(obj)


def table_from_iterator(
    data_iterator: Iterator[dict],
    schema: Optional[pa.Schema] = None,
    *,
    primary_keys: Optional[Sequence[str]] = None,
    binary_reporter: Optional[BinaryColumnReporter] = None,
) -> pa.Table:
    batch = list(data_iterator)
    if not batch:
        return pa.Table.from_pylist([])

    processed_batch = _process_batch(batch, schema, primary_keys=primary_keys, binary_reporter=binary_reporter)

    return processed_batch


def table_from_py_list(
    table_data: list[Any],
    schema: Optional[pa.Schema] = None,
    *,
    primary_keys: Optional[Sequence[str]] = None,
    binary_reporter: Optional[BinaryColumnReporter] = None,
) -> pa.Table:
    """
    Convert a list of Python dictionaries to a PyArrow Table.
    This is a wrapper around table_from_iterator for backward compatibility.
    """
    return table_from_iterator(
        iter(table_data), schema=schema, primary_keys=primary_keys, binary_reporter=binary_reporter
    )


def restrict_schema_to_columns(schema: pa.Schema, column_names: Sequence[str]) -> pa.Schema:
    """Drop fields from `schema` that aren't among `column_names`.

    `pa.Table.from_pydict` raises an opaque KeyError ("The passed mapping doesn't contain the
    following field(s) of the schema: ...") when the provided schema declares a column the row
    mapping lacks. A SQL source builds its Arrow schema from columns discovered during setup, but
    the streaming read can return a strict subset — e.g. a column dropped at the source, or the
    table recreated with a narrower shape, between discovery and the read. Restricting the schema
    to the columns the query actually returned lets the batch build; extra columns present in the
    rows but not the schema are still handled by `_process_batch`, which appends them.
    """
    present = set(column_names)
    if all(name in present for name in schema.names):
        return schema
    return pa.schema([field for field in schema if field.name in present])


def build_pyarrow_decimal_type(precision: int, scale: int) -> pa.Decimal128Type | pa.Decimal256Type:
    if precision <= 38:
        return pa.decimal128(precision, scale)
    elif precision <= 76:
        return pa.decimal256(precision, scale)
    else:
        return pa.decimal256(76, max(0, 76 - (precision - scale)))


def _get_max_decimal_type(values: list[decimal.Decimal]) -> pa.Decimal128Type | pa.Decimal256Type:
    """Determine maximum precision and scale from all `decimal.Decimal` values.

    Returns:
        A `pa.Decimal128Type` or `pa.Decimal256Type` with enough precision and
        scale to hold all `values`.
    """
    max_int_digits = 0
    max_scale = 0

    for value in values:
        _, digits, exponent = value.as_tuple()
        if not isinstance(exponent, int):
            continue

        # `len(digits) + exponent` is the number of digits left of the decimal point (<= 0 for a
        # pure fraction such as 0.0012). See Arrow's decimal inference:
        # https://github.com/apache/arrow/blob/main/python/pyarrow/src/arrow/python/decimal.cc#L75
        scale = -exponent if exponent < 0 else 0
        int_digits = max(len(digits) + exponent, 0)

        max_int_digits = max(int_digits, max_int_digits)
        max_scale = max(scale, max_scale)

    # Deltalake doesn't like writing decimals with scale of 0 - it auto appends `.0`
    if max_scale == 0:
        max_scale = 1

    # Precision must cover BOTH the integer and fractional parts. Taking the max precision and the
    # max scale independently under-provisions integer digits when the widest value and the
    # highest-scale value are different rows — e.g. [1000000, 0.0001] would infer a type with no
    # room for the 7-digit integer, overflowing the Delta write. Sizing precision as
    # integer-digits + scale keeps every value representable.
    max_precision = max(max_int_digits + max_scale, 1)

    return build_pyarrow_decimal_type(max_precision, max_scale)


def _quantize_to_scale(value: decimal.Decimal, scale: int) -> decimal.Decimal:
    quantum = decimal.Decimal(1).scaleb(-scale)
    with decimal.localcontext() as ctx:
        # Hold decimal256's full 76 digits while rounding so the quantize itself can't overflow.
        ctx.prec = 76
        return value.quantize(quantum, rounding=decimal.ROUND_HALF_EVEN)


def _decimal_array_from_values(values: list[decimal.Decimal | None]) -> pa.Array:
    non_null = [v for v in values if v is not None]
    if non_null:
        optimal_type = _get_max_decimal_type(non_null)
        try:
            return pa.array(values, type=optimal_type)
        except pa.ArrowInvalid:
            pass

    fallback_type = pa.decimal256(76, MAX_NUMERIC_SCALE)
    try:
        return pa.array(values, type=fallback_type)
    except Exception:
        # A value carries more decimal places than Delta Lake's max scale (e.g. an unconstrained
        # Postgres `numeric`). pyarrow refuses to silently truncate, so round to the max scale
        # ourselves rather than failing the whole sync.
        try:
            quantized = [None if v is None else _quantize_to_scale(v, MAX_NUMERIC_SCALE) for v in values]
            return pa.array(quantized, type=fallback_type)
        except Exception as exc:
            raise ValueError("Cannot build decimal array from values") from exc


def _decimal_values_from_column(column: pa.ChunkedArray) -> list[decimal.Decimal | None] | None:
    """Best-effort conversion of a column's values to Decimals, for a column expected to be decimal.

    Handles decimal columns directly and string columns — the pipeline (and dlt) stores a decimal
    that grew past decimal128 as text (decimal256 → string), so a batch column can arrive as
    strings even though its stored Delta column is decimal. Returns None when a non-null value
    can't be parsed as a decimal (a genuine decimal→text change, not a widened decimal), leaving
    that mismatch for the caller to ignore.
    """
    result: list[decimal.Decimal | None] = []
    for value in _to_list_array(column):
        if value is None:
            result.append(None)
        elif isinstance(value, decimal.Decimal):
            result.append(value)
        else:
            try:
                result.append(decimal.Decimal(str(value)))
            except (decimal.InvalidOperation, ValueError, TypeError):
                return None
    return result


def _fit_decimal_values_to_type(
    values: list[decimal.Decimal | None], target: pa.Decimal128Type | pa.Decimal256Type
) -> pa.Array | None:
    """Round `values` to `target`'s scale and build an array of exactly `target`.

    Rounding only drops fractional precision beyond the target scale, never integer digits.
    Returns None when a value's integer part exceeds the target's capacity (unrepresentable no
    matter the rounding) so the caller can treat it as an unrecoverable column-type mismatch.
    """
    try:
        quantized = [None if v is None else _quantize_to_scale(v, target.scale) for v in values]
    except decimal.InvalidOperation:
        return None
    try:
        return pa.array(quantized, type=target)
    except pa.ArrowInvalid:
        return None


def align_incoming_decimals_to_delta(pa_table: pa.Table, delta_schema: deltalake.Schema) -> pa.Table:
    """Reconcile a batch's decimal columns to the existing Delta table's decimal column types.

    A Delta merge casts every source column to its stored target column type, and delta-rs cannot
    widen a decimal column in place. When earlier schema inference stored a scale-heavy column
    (e.g. decimal128(38, 32), only 6 integer digits), a later, larger value overflows that implicit
    cast with an opaque ``DeltaError`` that retries forever. Pre-casting each batch column to the
    exact stored type makes the merge cast a no-op: fitting values are rounded to the column's
    scale, and a value whose integer part can't fit is surfaced as SchemaColumnTypeChangedException
    so the sync stops and the table can be reset and re-synced (which recreates the column with
    adequate integer headroom).
    """
    delta_arrow_schema = pyarrow_schema_from_arrow_exportable(delta_schema)
    for delta_field in delta_arrow_schema:
        if not pa.types.is_decimal(delta_field.type) or delta_field.name not in pa_table.schema.names:
            continue

        column = pa_table.column(delta_field.name)
        if column.type == delta_field.type:
            continue
        if not (
            pa.types.is_decimal(column.type) or pa.types.is_string(column.type) or pa.types.is_large_string(column.type)
        ):
            # A decimal column paired with a non-decimal, non-text batch column is a different
            # mismatch handled by evolve_pyarrow_schema; leave it alone.
            continue

        values = _decimal_values_from_column(column)
        if values is None:
            continue

        target = cast(pa.Decimal128Type | pa.Decimal256Type, delta_field.type)
        aligned = _fit_decimal_values_to_type(values, target)
        if aligned is None:
            raise SchemaColumnTypeChangedException(
                f"Source column type changed: '{delta_field.name}' has decimal values that no longer "
                f"fit its stored type {delta_field.type}. Reset and fully re-sync this table to adopt "
                f"a wider type."
            )
        pa_table = pa_table.set_column(pa_table.schema.get_field_index(delta_field.name), delta_field.name, aligned)

    return pa_table


def relax_batch_nullability(pa_table: pa.Table) -> pa.Table:
    """Mark every batch column that actually holds nulls as nullable in the batch's own schema.

    SQL sources build the batch schema from the source database's own `is_nullable` metadata, so a
    column the source declares NOT NULL can still arrive holding nulls: the value was dropped by a
    projection or a join, or its conversion failed. pyarrow does not check the claim when it builds
    the table in Python, so the batch reaches the writers with a schema that contradicts its data.

    Every delta path checks it and refuses the batch: `write_deltalake` raises a DeltaError,
    `DeltaTable.merge` panics in Rust before it can plan the merge, and deltalite's
    `RecordBatch::try_new` rejects it, which sends the write to the MERGE that then panics. All
    three report "declared as non-nullable but contains null values". Correcting the claim before
    the write also lets deltalite relax a stored column that a past batch already poisoned.

    The cast rewrites field metadata only, so the column buffers are shared and not copied.
    """
    relaxed: list[pa.Field] = []
    changed = False
    for index, field in enumerate(pa_table.schema):
        if not field.nullable and pa_table.column(index).null_count > 0:
            relaxed.append(field.with_nullable(True))
            changed = True
        else:
            relaxed.append(field)

    if not changed:
        return pa_table

    return pa_table.cast(pa.schema(relaxed).with_metadata(pa_table.schema.metadata or {}))


def raise_on_nullability_drift(pa_table: pa.Table, delta_schema: deltalake.Schema) -> None:
    """Stop the sync when a batch has nulls in a column the table declares non-nullable.

    delta-rs cannot write a null into a non-nullable column, and deltalake 1.6.1 has no operation to
    relax an existing column to nullable in place. So a source that starts emitting nulls in a
    column the table created non-nullable is a schema change under the table, and the only fix is to
    reset and fully re-sync it -- which recreates the column as nullable. Surfaced as
    SchemaColumnTypeChangedException, the same reset-and-re-sync signal the decimal-widening path
    uses, so the sync stops non-retryably instead of failing opaquely (deltalite) or silently
    writing the nulls into a lying non-nullable schema (the delta-rs MERGE fallback).
    """
    delta_arrow_schema = pyarrow_schema_from_arrow_exportable(delta_schema)
    for delta_field in delta_arrow_schema:
        if delta_field.nullable or delta_field.name not in pa_table.schema.names:
            continue
        if pa_table.column(delta_field.name).null_count > 0:
            raise SchemaColumnTypeChangedException(
                f"Source column '{delta_field.name}' now contains nulls, but the table declares it "
                f"non-nullable. Reset and fully re-sync this table to recreate the column as nullable."
            )


def _python_type_to_pyarrow_type(type_: type, value: Any):
    python_to_pa = {
        int: pa.int64(),
        float: pa.float64(),
        str: pa.string(),
        bool: pa.bool_(),
        bytes: pa.binary(),
        type(None): pa.null(),
    }

    if type_ in python_to_pa:
        return python_to_pa[type_]

    if issubclass(type_, dict) and isinstance(value, dict):
        return pa.struct([pa.field(str(k), _python_type_to_pyarrow_type(type(v), v)) for k, v in value.items()])

    if issubclass(type_, list) and isinstance(value, list):
        if len(value) == 0:
            return pa.list_(pa.null())

        return pa.list_(_python_type_to_pyarrow_type(type(value[0]), value[0]))

    if issubclass(type_, decimal.Decimal) and isinstance(value, decimal.Decimal):
        sign, digits, exponent = value.as_tuple()
        if isinstance(exponent, int):
            precision = len(digits)
            scale = -exponent if exponent < 0 else 0

            return build_pyarrow_decimal_type(precision, scale)

        return pa.decimal256(DEFAULT_NUMERIC_PRECISION, DEFAULT_NUMERIC_SCALE)

    # `datetime` before `date`: `datetime.datetime` subclasses `datetime.date`.
    if issubclass(type_, datetime.datetime) and isinstance(value, datetime.datetime):
        return pa.timestamp("us", tz="UTC") if value.tzinfo is not None else pa.timestamp("us")

    if issubclass(type_, datetime.date) and isinstance(value, datetime.date):
        return pa.date32()

    if issubclass(type_, datetime.time) and isinstance(value, datetime.time):
        return pa.time64("us")

    # UUID values are stringified later in `_process_batch`; declare the field as string here so a
    # UUID column absent from the provided schema doesn't crash while its field is being appended.
    if issubclass(type_, uuid.UUID):
        return pa.string()

    raise ValueError(f"Python type {type_} has no pyarrow mapping")


def _to_list_array(column_data: pa.Array | pa.ChunkedArray | np.ndarray[Any, np.dtype[Any]]):
    if isinstance(column_data, pa.ChunkedArray):
        try:
            return column_data.combine_chunks().tolist()
        except pa.ArrowInvalid as e:
            joined_args = "".join(e.args)
            if "consider casting input from `string` to `large_string`" in joined_args:
                return column_data.cast(pa.large_string()).combine_chunks().tolist()
            # Same int32 offset overflow as above, for `binary`-typed columns (e.g. a Postgres
            # `bytea` whose chunk exceeds 2GB). large_binary uses 64-bit offsets so combining
            # the chunks no longer overflows.
            if "consider casting input from `binary` to `large_binary`" in joined_args:
                return column_data.cast(pa.large_binary()).combine_chunks().tolist()

            raise

    return column_data.tolist()


def _serialize_dict_columns(table_data: list[dict]) -> tuple[list[dict], set[str]]:
    """JSON-serialize columns whose non-None values are all dicts, before any Arrow work.

    Such a column ends up stored as a JSON string either way, but letting it reach `pa.array()`
    first builds a unified struct type whose field count is the union of every row's key paths.
    For heterogeneous nested documents (e.g. a MongoDB collection where each document's structure
    varies) that union grows with the batch, making conversion superlinear in rows — batches of a
    few hundred documents can take minutes and starve activity heartbeats. The struct round-trip
    also injects the union's null-filled fields into every serialized row, bloating the stored
    JSON with keys the original document never had. Serializing the source dicts up front keeps
    conversion linear and preserves each document exactly.

    The caller's rows are left untouched — rows needing serialization are shallow-copied — so
    reusing or retrying with the same batch stays safe. Returns the (possibly new) row list and
    the serialized column names so a provided schema can be coerced to string for them.
    """
    dict_columns: set[str] = set()
    non_dict_columns: set[str] = set()
    for row in table_data:
        for key, value in row.items():
            if value is None or key in non_dict_columns:
                continue
            if isinstance(value, dict):
                dict_columns.add(key)
            else:
                non_dict_columns.add(key)
                dict_columns.discard(key)

    if not dict_columns:
        return table_data, dict_columns

    serialized_rows: list[dict] = []
    for row in table_data:
        replaced: Optional[dict] = None
        for key in dict_columns:
            value = row.get(key)
            if value is not None:
                if replaced is None:
                    replaced = dict(row)
                replaced[key] = _json_dumps(value)
        serialized_rows.append(replaced if replaced is not None else row)

    return serialized_rows, dict_columns


def _process_batch(
    table_data: list[dict],
    schema: Optional[pa.Schema] = None,
    *,
    primary_keys: Optional[Sequence[str]] = None,
    binary_reporter: Optional[BinaryColumnReporter] = None,
) -> pa.Table:
    table_data, serialized_dict_columns = _serialize_dict_columns(table_data)

    # Support both given schemas and inferred schemas
    if schema is None or len(schema.names) == 0:
        try:
            # Gather all unique keys from all items, not just the first
            all_keys = set().union(*(d.keys() for d in table_data))
            first_item = table_data[0]
            first_item = {key: first_item.get(key, None) for key in all_keys}
            table_data[0] = first_item
            arrow_schema = pa.Table.from_pylist(table_data).schema
        except:
            arrow_schema = None
    else:
        arrow_schema = schema

    drop_column_names: set[str] = set()

    column_names = set(table_data[0].keys())
    columnar_table_data: dict[str, pa.Array | np.ndarray[Any, np.dtype[Any]]] = {}

    for col in column_names:
        values: list[object | None] = []
        for row in table_data:
            value = row.get(col, None)
            if isinstance(value, float) and np.isnan(value):
                values.append(None)
            else:
                values.append(value)

        try:
            # We want to use pyarrow arrays where possible to optimise on memory usage
            columnar_table_data[col] = pa.array(values)
        except:
            # Some values can't be interpreted by pyarrows directly
            columnar_table_data[col] = np.array(values, dtype=object)

    for field_name in columnar_table_data.keys():
        py_type: type = type(None)
        unique_types_in_column = {
            type(item) for item in _to_list_array(columnar_table_data[field_name]) if item is not None
        }

        for row in table_data:
            val = row.get(field_name, None)
            if val is not None:
                py_type = type(val)
                break

        # If a schema is present:
        if arrow_schema:
            if field_name not in arrow_schema.names:
                new_field = pa.field(str(field_name), _python_type_to_pyarrow_type(py_type, val), nullable=True)
                arrow_schema = arrow_schema.append(field=new_field)

            field = arrow_schema.field_by_name(str(field_name))
            field_index = arrow_schema.get_field_index(str(field_name))

            # A serialized dict column holds JSON strings now; a provided schema may still declare
            # the source's original non-string type for it, which from_pydict would fail to cast.
            if (
                field_name in serialized_dict_columns
                and not pa.types.is_string(field.type)
                and not pa.types.is_large_string(field.type)
            ):
                arrow_schema = arrow_schema.set(field_index, field.with_type(pa.string()))
                field = arrow_schema.field_by_name(str(field_name))

            # cast double / float ndarrays to decimals if type mismatch, looks like decimals and floats are often mixed up in dialects
            if pa.types.is_decimal(field.type) and (float in unique_types_in_column or str in unique_types_in_column):
                float_array = pa.array(columnar_table_data[field_name], type=pa.float64())
                columnar_table_data[field_name] = float_array.cast(field.type, safe=False)
                unique_types_in_column = {decimal.Decimal}
                py_type = decimal.Decimal
                val = decimal.Decimal(cast(DecimalInput, val))

            # cast string timestamps to datetime objects
            if pa.types.is_timestamp(field.type) and issubclass(py_type, str):
                timestamp_array = pa.array(
                    [safe_parse_datetime(s) for s in _to_list_array(columnar_table_data[field_name])], type=field.type
                )
                columnar_table_data[field_name] = timestamp_array
                has_nulls = pc.any(pc.is_null(timestamp_array)).as_py()

                adjusted_field = arrow_schema.field(field_index).with_nullable(has_nulls)
                arrow_schema = arrow_schema.set(field_index, adjusted_field)

            # Upscale second timestamps to microsecond
            if pa.types.is_timestamp(field.type) and issubclass(py_type, int) and field.type.unit == "s":
                timestamp_array = pa.array(
                    [
                        (s * 1_000_000) if s is not None else None
                        for s in _to_list_array(columnar_table_data[field_name])
                    ],
                    type=pa.timestamp("us"),
                )
                columnar_table_data[field_name] = timestamp_array
                has_nulls = pc.any(pc.is_null(timestamp_array)).as_py()
                adjusted_field = arrow_schema.field(field_index).with_type(pa.timestamp("us")).with_nullable(has_nulls)
                arrow_schema = arrow_schema.set(field_index, adjusted_field)

            # Upscale millisecond timestamps to microsecond
            if pa.types.is_timestamp(field.type) and issubclass(py_type, int) and field.type.unit == "ms":
                timestamp_array = pa.array(
                    [(s * 1000) if s is not None else None for s in _to_list_array(columnar_table_data[field_name])],
                    type=pa.timestamp("us"),
                )
                columnar_table_data[field_name] = timestamp_array
                has_nulls = pc.any(pc.is_null(timestamp_array)).as_py()
                adjusted_field = arrow_schema.field(field_index).with_type(pa.timestamp("us")).with_nullable(has_nulls)
                arrow_schema = arrow_schema.set(field_index, adjusted_field)

            # Binary columns can't be queried, so they are dropped; id-like ones are kept as hex
            # strings because they are usually the table's key, and losing the key breaks joins
            # and incremental merges on the synced table.
            if pa.types.is_binary(field.type):
                if _is_id_like_column(str(field_name), primary_keys):
                    hex_arrays = _hex_arrays_or_report(
                        [_to_list_array(columnar_table_data[field_name])],
                        str(field_name),
                        binary_reporter,
                        pa.string(),
                    )
                    if hex_arrays is None:
                        drop_column_names.add(field_name)
                    else:
                        columnar_table_data[field_name] = hex_arrays[0]
                        py_type = str
                        unique_types_in_column = {str}
                        arrow_schema = arrow_schema.set(
                            field_index, arrow_schema.field(field_index).with_type(pa.string())
                        )
                else:
                    if binary_reporter:
                        binary_reporter.dropped(str(field_name))
                    drop_column_names.add(field_name)

            # Ensure duration columns have the correct arrow type
            col = columnar_table_data[field_name]
            if (
                isinstance(col, pa.Array)
                and pa.types.is_duration(col.type)
                and not pa.types.is_duration(arrow_schema.field(field_index).type)
            ):
                arrow_schema = arrow_schema.set(field_index, arrow_schema.field(field_index).with_type(col.type))

        # Convert UUIDs to strings
        if issubclass(py_type, uuid.UUID):
            uuid_str_array = pa.array(
                [None if s is None else str(s) for s in _to_list_array(columnar_table_data[field_name])]
            )
            columnar_table_data[field_name] = uuid_str_array
            py_type = str
            if arrow_schema:
                arrow_schema = arrow_schema.set(field_index, arrow_schema.field(field_index).with_type(pa.string()))

        # Remove any NaN or infinite values from decimal columns
        if issubclass(py_type, decimal.Decimal) or issubclass(py_type, float):

            def _convert_to_decimal_or_none(x: decimal.Decimal | float | str | None) -> decimal.Decimal | None:
                if x is None:
                    return None

                if isinstance(x, str):
                    stripped = x.strip()
                    if stripped == "":
                        return None
                    try:
                        x = decimal.Decimal(stripped)
                    except decimal.InvalidOperation:
                        # A genuinely non-numeric value in a column imported as a number; the caller adds column context.
                        raise TypeError("must be real number, not str")

                if (
                    math.isnan(x)
                    or (isinstance(x, decimal.Decimal) and x.is_infinite())
                    or (isinstance(x, float) and np.isinf(x))
                ):
                    return None

                if isinstance(x, decimal.Decimal):
                    return x

                return decimal.Decimal(str(x))

            def _convert_to_float_or_none(x: float | str | None) -> float | None:
                if x is None:
                    return None

                if isinstance(x, str):
                    stripped = x.strip()
                    if stripped == "":
                        return None
                    try:
                        x = float(stripped)
                    except ValueError:
                        raise TypeError("must be real number, not str")

                if math.isnan(x) or np.isinf(x):
                    return None

                return x

            all_values = _to_list_array(columnar_table_data[field_name])

            if len(unique_types_in_column) > 1 or issubclass(py_type, decimal.Decimal):
                # Mixed types: convert all to decimals
                try:
                    all_values = [_convert_to_decimal_or_none(x) for x in all_values]
                except TypeError as e:
                    # A column imported as a number contains a non-numeric value (text, or a
                    # blank cell that arrives as ""). Keep the original "must be real number,
                    # not str" phrase so source non-retryable matching still fires, but name the
                    # column and show examples so the offending cells can be found in the source.
                    offenders = [x for x in all_values if isinstance(x, str)]
                    sample = [(x if x != "" else "<blank>") for x in offenders[:5]]
                    raise TypeError(
                        f"must be real number, not str: column '{field_name}' is imported as a "
                        f"number but contains {len(offenders)} non-numeric value(s) such as "
                        f"{sample}. Ensure every cell in this column is a plain number (or empty)."
                    ) from e

                if arrow_schema and pa.types.is_decimal(arrow_schema.field(field_index).type):
                    new_field_type = arrow_schema.field(field_index).type
                else:
                    new_field_type = _get_max_decimal_type([x for x in all_values if x is not None])

                py_type = decimal.Decimal
                unique_types_in_column = {decimal.Decimal}
            elif issubclass(py_type, float):
                all_values = [_convert_to_float_or_none(x) for x in all_values]

                if arrow_schema:
                    new_field_type = arrow_schema.field(field_index).type
                else:
                    new_field_type = pa.float64()

            try:
                number_arr = pa.array(
                    all_values,
                    type=new_field_type,
                )
            except pa.ArrowInvalid as e:
                if len(e.args) > 0 and (
                    "does not fit into precision" in e.args[0] or "would cause data loss" in e.args[0]
                ):
                    decimal_values = (
                        all_values
                        if py_type is decimal.Decimal
                        else [_convert_to_decimal_or_none(x) for x in all_values]
                    )
                    try:
                        number_arr = _decimal_array_from_values(decimal_values)
                        new_field_type = number_arr.type
                        py_type = decimal.Decimal
                        unique_types_in_column = {decimal.Decimal}
                    except ValueError:
                        # A value is too large even for decimal256 (e.g. an unconstrained Postgres
                        # `numeric` with more than 76 significant digits) — keep the column as text
                        # rather than crash the sync, mirroring the huge-int fallback below.
                        number_arr = pa.array([None if v is None else str(v) for v in decimal_values], type=pa.string())
                        new_field_type = pa.string()
                        py_type = str
                        unique_types_in_column = {str}
                else:
                    raise

            columnar_table_data[field_name] = number_arr
            if arrow_schema:
                arrow_schema = arrow_schema.set(field_index, arrow_schema.field(field_index).with_type(new_field_type))

        # Integer columns can hold Python ints larger than pyarrow's int64 range (e.g. a Google
        # Sheets cell with a huge number). pyarrow raises "OverflowError: Python int too large to
        # convert to C long" while inferring int64. Such a column already failed `pa.array(values)`
        # above and fell back to an object ndarray, so restrict the scan to those candidates to
        # avoid touching every normal int column. Promote to decimal when it fits, else stringify.
        if (
            py_type is int
            and unique_types_in_column == {int}
            and isinstance(columnar_table_data[field_name], np.ndarray)
        ):
            all_values = _to_list_array(columnar_table_data[field_name])
            if any(value is not None and not (INT64_MIN <= value <= INT64_MAX) for value in all_values):
                try:
                    overflow_arr = _decimal_array_from_values(
                        [None if value is None else decimal.Decimal(value) for value in all_values]
                    )
                    py_type = decimal.Decimal
                    unique_types_in_column = {decimal.Decimal}
                except ValueError:
                    # Too large even for decimal256 — keep it as text rather than crash the sync.
                    overflow_arr = pa.array(
                        [None if value is None else str(value) for value in all_values], type=pa.string()
                    )
                    py_type = str
                    unique_types_in_column = {str}

                columnar_table_data[field_name] = overflow_arr
                if arrow_schema:
                    arrow_schema = arrow_schema.set(
                        field_index, arrow_schema.field(field_index).with_type(overflow_arr.type)
                    )

        # If one type is a list, wrap scalars into single-element lists and JSON-stringify the column.
        # Element types can differ across rows (e.g. a WordPress field returned as a bool in one row
        # and an object in another), which no single pyarrow list type can hold, so serialize directly
        # rather than via an intermediate list array that would raise ArrowInvalid on the mismatch.
        if len(unique_types_in_column) > 1 and list in unique_types_in_column:
            json_array = pa.array(
                [
                    None if s is None else _json_dumps(s if isinstance(s, list) else [s])
                    for s in _to_list_array(columnar_table_data[field_name])
                ]
            )
            columnar_table_data[field_name] = json_array
            py_type = str
            unique_types_in_column = {str}
            if arrow_schema:
                arrow_schema = arrow_schema.set(field_index, arrow_schema.field(field_index).with_type(pa.string()))

        # If str and dict are shared - then turn everything into a json string. A column can also
        # carry a third type alongside them (e.g. an int, as with a free-form field that varies per
        # row) — JSON-dump anything that isn't already a string rather than only dict/list, so that
        # third type doesn't reach pa.array() unconverted and raise ArrowTypeError.
        if len(unique_types_in_column) > 1 and str in unique_types_in_column and dict in unique_types_in_column:
            json_array = pa.array(
                [
                    None if s is None else s if isinstance(s, str) else _json_dumps(s)
                    for s in _to_list_array(columnar_table_data[field_name])
                ]
            )
            columnar_table_data[field_name] = json_array
            py_type = str
            unique_types_in_column = {str}
            if arrow_schema:
                arrow_schema = arrow_schema.set(field_index, arrow_schema.field(field_index).with_type(pa.string()))

        # If there are multiple types that aren't a list, then JSON stringify everything
        if len(unique_types_in_column) > 1:
            json_array = pa.array(
                [None if s is None else _json_dumps(s) for s in _to_list_array(columnar_table_data[field_name])]
            )
            columnar_table_data[field_name] = json_array
            py_type = str
            unique_types_in_column = {str}
            if arrow_schema:
                arrow_schema = arrow_schema.set(field_index, arrow_schema.field(field_index).with_type(pa.string()))

        # Convert any dict/lists to json strings to avoid schema mismatches in nested objects
        if issubclass(py_type, dict | list):
            json_str_array = pa.array(
                [None if s is None else _json_dumps(s) for s in _to_list_array(columnar_table_data[field_name])]
            )
            columnar_table_data[field_name] = json_str_array
            py_type = str
            if arrow_schema:
                arrow_schema = arrow_schema.set(field_index, arrow_schema.field(field_index).with_type(pa.string()))

        # Convert IP types to string
        if issubclass(py_type, IPv4Address | IPv6Address):
            str_array = pa.array(
                [None if s is None else str(s) for s in _to_list_array(columnar_table_data[field_name])]
            )
            columnar_table_data[field_name] = str_array
            py_type = str
            if arrow_schema:
                arrow_schema = arrow_schema.set(field_index, arrow_schema.field(field_index).with_type(pa.string()))

        # Same keep-or-drop rule as the schema-typed binary branch above; this one catches
        # columns whose binary type is only visible from the Python values (e.g. inferred
        # schemas, or a declared type the values don't match).
        if issubclass(py_type, bytes):
            if _is_id_like_column(str(field_name), primary_keys):
                hex_arrays = _hex_arrays_or_report(
                    [_to_list_array(columnar_table_data[field_name])], str(field_name), binary_reporter, pa.string()
                )
                if hex_arrays is None:
                    drop_column_names.add(field_name)
                else:
                    columnar_table_data[field_name] = hex_arrays[0]
                    py_type = str
                    if arrow_schema:
                        arrow_schema = arrow_schema.set(
                            field_index, arrow_schema.field(field_index).with_type(pa.string())
                        )
            else:
                if binary_reporter:
                    binary_reporter.dropped(str(field_name))
                drop_column_names.add(field_name)

    if len(drop_column_names) != 0:
        for column in drop_column_names:
            del columnar_table_data[column]
            if arrow_schema:
                arrow_schema = arrow_schema.remove(arrow_schema.get_field_index(str(column)))

    return pa.Table.from_pydict(columnar_table_data, schema=arrow_schema)


# from `conditional-cache`, but changed to be made async
def conditional_lru_cache_async(
    maxsize: int = 128, typed: bool = False, condition: Callable[[Any], bool] = lambda x: True
):
    cache = CircularDict(maxlen=maxsize)

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            key = _make_key(args, kwargs, typed)

            if key in cache:
                return cache[key]

            result = await func(*args, **kwargs)

            if condition(result):
                cache[key] = result

            return result

        def cache_remove(*args, **kwargs):
            key = _make_key(args, kwargs, typed)
            cache.pop(key, None)

        def cache_pop(*args, **kwargs) -> Any:
            """Remove and return a cached value without ever invoking `func` — unlike calling
            `wrapper` itself, a cache miss returns `None` instead of computing and storing a
            fresh result. For callers that only want to release an already-cached resource.

            Checks membership before popping: CircularDict.pop(key, None) treats a `None`
            default as "no default" and raises KeyError on a miss instead of returning it.
            """
            key = _make_key(args, kwargs, typed)
            if key not in cache:
                return None
            return cache.pop(key)

        cast(Any, wrapper).cache_remove = cache_remove
        cast(Any, wrapper).cache_clear = lambda: cache.clear()
        cast(Any, wrapper).cache_pop = cache_pop

        return wrapper

    return decorator


def realign_decimal_buffers(table: pa.Table) -> pa.Table:
    """Re-materialize any Decimal128/256 column whose values buffer isn't 16-byte aligned.

    delta-rs (arrow-rs) aborts the entire worker — not a catchable Python exception,
    an `abort()` at the `extern "C"` boundary that can't unwind — when it's handed a
    decimal values buffer aligned to 8 bytes instead of the 16 that Rust's i128 requires.
    The misalignment arrives across the Arrow C Data Interface, which only recommends
    8-byte alignment. Every Delta write/merge is funneled through here so a single guard
    covers both pipeline versions. See delta-io/delta-rs#3884.

    Only the values buffer (`buffers()[1]`) holds the i128 payload that must be aligned;
    the validity bitmap has no such requirement, so we don't bother checking it.

    `pa.concat_arrays` forces a fresh allocation through pyarrow's allocator (64-byte
    aligned), which satisfies the requirement. `combine_chunks()` is zero-copy and would
    keep the misaligned buffer, so it can't be used here. The buffer scan is cheap and
    the copy only fires on the rare misaligned batch, so the common path is untouched.
    """
    new_columns: dict[str, pa.ChunkedArray] = {}
    realigned = False
    for i in range(table.num_columns):
        field = table.field(i)
        column = table.column(i)
        if pa.types.is_decimal(field.type) and any(
            (values := chunk.buffers()[1]) is not None and values.address % 16 for chunk in column.chunks
        ):
            # concat_arrays preserves the chunks' (decimal) type; pyarrow-stubs has no
            # chunked_array overload for an explicit decimal type=.
            new_columns[field.name] = pa.chunked_array([pa.concat_arrays(column.chunks)])
            realigned = True
        else:
            new_columns[field.name] = column

    if not realigned:
        return table

    return pa.table(new_columns, schema=table.schema)


def first_per_pk_table(pa_table: pa.Table, pk_columns: list[str], keep: Literal["first", "last"] = "first") -> pa.Table:
    """Return a table containing only one row per PK tuple (in original row order).

    `keep` picks which occurrence survives: "first" is used when closing existing
    "current" rows during SCD2 append; "last" is used to dedupe upsert batches, where
    the latest occurrence of a key carries the freshest data. Either way the merge
    receives at most one source row per key, avoiding ambiguous multi-match merge
    semantics (and the duplicate inserts `when_not_matched_insert_all` would produce).
    """
    if not pk_columns or pa_table.num_rows == 0:
        return pa_table

    # Strategy: tag every row with its position, group by PK, and for each PK
    # take the smallest (or largest) position — the first (or last) time we saw
    # that PK. Sorting those positions at the end restores the original row order.
    #
    # We use numpy for the final sort because pyarrow's type stubs for
    # `pc.sort_indices` / `Array.take` are currently broken — numpy's stubs work.
    idx_col_name = "__ph_cdc_row_idx"
    aggregate: Literal["min", "max"] = "min" if keep == "first" else "max"

    # 1. Add a row-position column: [0, 1, 2, ..., n-1]
    indexed = pa_table.append_column(idx_col_name, pa.array(range(pa_table.num_rows), type=pa.int64()))

    # 2. Group by PK, keeping only one position per PK
    grouped = indexed.group_by(pk_columns).aggregate([(idx_col_name, aggregate)])

    # 3. Sort those positions ascending so the output mirrors the input row order
    kept_indices = np.sort(grouped.column(f"{idx_col_name}_{aggregate}").to_numpy())

    # 4. Materialize the rows at those positions from the original table
    return pa_table.take(kept_indices)
