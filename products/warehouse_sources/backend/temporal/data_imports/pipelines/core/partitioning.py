from __future__ import annotations

import math
import hashlib
import datetime
from typing import TYPE_CHECKING, Any, Optional, cast

import pyarrow as pa
import deltalake as deltalake
import pyarrow.compute as pc
from dateutil import parser
from structlog.types import FilteringBoundLogger

from posthog.sync import database_sync_to_async_pool

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import normalize_column_name
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.consts import PARTITION_KEY
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    PartitionFormat,
    PartitionMode,
    SourceResponse,
)
from products.warehouse_sources.backend.types import IncrementalFieldType

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES = 200 * 1024 * 1024  # 200 MB

PARTITION_DATETIME_COLUMN_NAMES = ["created_at", "inserted_at", "createdAt"]

# Bucket for rows whose numerical partition key is null — they can't be bucketed arithmetically.
NULL_NUMERICAL_PARTITION = "null"

# Datetime-shaped incremental field types usable as a datetime partition key.
_DATETIME_INCREMENTAL_FIELD_TYPES = (
    IncrementalFieldType.Date,
    IncrementalFieldType.DateTime,
    IncrementalFieldType.Timestamp,
)


def _estimate_fallback_md5_partition_count(pa_table: pa.Table, rows_to_sync: int | None) -> int:
    """Bucket count for an md5 fallback, sized so each partition's working set stays near the target.

    Estimates total bytes as (avg bytes/row from this first batch) x (rows_to_sync, falling back to the
    batch's own row count when the source can't estimate). Uses the batch's in-memory Arrow size, which
    is the right proxy for the merge working set that OOMs (the at-rest compressed size undercounts it).
    """
    if pa_table.num_rows == 0:
        return 1
    avg_row_bytes = pa_table.nbytes / pa_table.num_rows
    total_rows = rows_to_sync if rows_to_sync and rows_to_sync > 0 else pa_table.num_rows
    estimated_total_bytes = avg_row_bytes * total_rows
    return max(1, math.ceil(estimated_total_bytes / DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES))


def _resolve_fallback_partition_scheme(
    pa_table: pa.Table,
    schema: ExternalDataSchema,
    partition_keys: list[str],
    rows_to_sync: int | None,
    logger: FilteringBoundLogger,
) -> tuple[PartitionMode, list[str], int | None] | None:
    """A partition scheme for a table the built-in auto-detect couldn't place.

    `append_partition_key_to_table` only recognizes an explicit count (md5), an incrementing integer
    primary key (numerical), or a `created_at`/`inserted_at`/`createdAt` timestamp column (datetime). A
    table whose timestamp is named differently (e.g. `received_at`, `segments_date`) or whose only key
    is a string/UUID falls through to no mode and writes unpartitioned — the whole table then loads into
    memory on every merge and OOMs the worker as it grows. This fills that gap so such a table is
    partitioned from its first load:

    - Prefer the schema's incremental field as a datetime key when it's a timestamp/date present in the
      data (keeps time-range pruning for later queries and incremental merges).
    - Otherwise md5 over the primary keys, with a count sized to the estimated total bytes.

    Returns None only when there is genuinely nothing to bucket on (no datetime field, no keys).
    """
    incremental_field = schema.incremental_field
    if incremental_field is not None and schema.incremental_field_type in _DATETIME_INCREMENTAL_FIELD_TYPES:
        column = normalize_column_name(incremental_field)
        if column in pa_table.column_names:
            column_type = pa_table.field(column).type
            has_values = pa_table.column(column).null_count != pa_table.num_rows
            if (pa.types.is_timestamp(column_type) or pa.types.is_date(column_type)) and has_values:
                logger.debug(f"partition fallback: datetime on incremental field {column}")
                return "datetime", [column], None

    if partition_keys:
        count = _estimate_fallback_md5_partition_count(pa_table, rows_to_sync)
        logger.debug(f"partition fallback: md5 over {partition_keys} with count={count}")
        return "md5", [normalize_column_name(key) for key in partition_keys], count

    return None


async def setup_partitioning(
    pa_table: pa.Table,
    existing_delta_table: deltalake.DeltaTable | None,
    schema: ExternalDataSchema,
    resource: SourceResponse,
    logger: FilteringBoundLogger,
) -> pa.Table:
    # An operator-pinned override (set via the admin repartition action) wins over both the
    # persisted auto-detected value and the source's freshly-computed value. Without this,
    # the reset bundled with repartition wipes `partition_count`/`partition_size`, and a SQL
    # source silently re-derives its own count — discarding the operator's choice.
    partition_count = schema.partition_count_override or schema.partition_count or resource.partition_count
    partition_size = schema.partition_size_override or schema.partition_size or resource.partition_size
    partition_keys = (
        schema.partitioning_keys_override
        or schema.partitioning_keys
        or resource.partition_keys
        or resource.primary_keys
    )
    partition_format = schema.partition_format or resource.partition_format
    partition_mode = schema.partition_mode_override or schema.partition_mode or resource.partition_mode

    if not partition_keys:
        logger.debug("No partition keys, skipping partitioning")
        return pa_table

    if existing_delta_table:
        # Check the table's *partition columns* — not its schema columns. A delta
        # table can contain `_ph_partition_key` in its schema without being
        # partitioned by it (e.g. leftover from a prior write that included the
        # column but was committed with `partition_by=None`). Writing with
        # `partition_by=PARTITION_KEY` in that case raises
        # `DeltaError: Specified table partitioning does not match table partitioning`.
        partition_columns = getattr(existing_delta_table.metadata(), "partition_columns", None) or []
        if PARTITION_KEY not in partition_columns:
            logger.debug("Delta table already exists without partitioning, skipping partitioning")
            return pa_table

    partition_result = append_partition_key_to_table(
        table=pa_table,
        partition_count=partition_count,
        partition_size=partition_size,
        partition_keys=partition_keys,
        partition_mode=partition_mode,
        partition_format=partition_format,
        logger=logger,
    )

    if partition_result is None:
        # The built-in auto-detect found no usable mode (no explicit count, no incrementing int key, no
        # created_at-ish column). Fall back to the incremental timestamp field or an md5 bucketing over
        # the keys so the table is partitioned on this first load rather than written unpartitioned.
        fallback = _resolve_fallback_partition_scheme(pa_table, schema, partition_keys, resource.rows_to_sync, logger)
        if fallback is not None:
            fallback_mode, fallback_keys, fallback_count = fallback
            partition_count = fallback_count
            partition_result = append_partition_key_to_table(
                table=pa_table,
                partition_count=fallback_count,
                partition_size=partition_size,
                partition_keys=fallback_keys,
                partition_mode=fallback_mode,
                partition_format=partition_format,
                logger=logger,
            )

    if partition_result is not None:
        pa_table, partition_mode, partition_format, updated_partition_keys = partition_result

        if (
            not schema.partitioning_enabled
            or schema.partition_mode != partition_mode
            or schema.partition_format != partition_format
            or schema.partitioning_keys != updated_partition_keys
        ):
            logger.debug(
                f"Setting partitioning_enabled on schema with: partition_keys={partition_keys}. partition_count={partition_count}. partition_mode={partition_mode}. partition_format={partition_format}"
            )
            await database_sync_to_async_pool(schema.set_partitioning_enabled)(
                updated_partition_keys, partition_count, partition_size, partition_mode, partition_format
            )

    return pa_table


_DATETIME_STRFTIME_FORMATS: dict[PartitionFormat, str] = {
    "hour": "%Y-%m-%dT%H",
    "day": "%Y-%m-%d",
    "week": "%G-w%V",
    "month": "%Y-%m",
}
# Bucket for a row whose partition value can't be parsed as a date (empty/garbage string). A single
# catch-all bucket, kept distinct from any real date.
_UNKNOWN_DATETIME_BUCKET = "1970-01"


def _md5_partition_bucket(row: dict[str, Any], keys: list[str], partition_count: int) -> str:
    # Read via `row.get` so a partition key missing from a drifted batch buckets into a stable
    # fallback (`str(None)`) instead of raising KeyError and failing the whole sync.
    delimited = "|".join(str(row.get(key)) for key in keys)
    # this hash has no security impact
    # nosemgrep: python.lang.security.insecure-hash-algorithms-md5.insecure-hash-algorithm-md5
    hash_value = int(hashlib.md5(delimited.encode()).hexdigest(), 16)
    return str(hash_value % partition_count)


def _datetime_partition_bucket(value: Any, partition_format: PartitionFormat) -> str:
    date_format = _DATETIME_STRFTIME_FORMATS[partition_format]
    date = value
    if isinstance(date, int):
        date = datetime.datetime.fromtimestamp(date)
    elif isinstance(date, str):
        if not date.strip():
            return _UNKNOWN_DATETIME_BUCKET
        try:
            date = parser.parse(date)
        except (ValueError, OverflowError):
            # Non-date-like string (e.g. a UUID primary key).
            return _UNKNOWN_DATETIME_BUCKET
    # datetime.datetime is a subclass of datetime.date, so this covers both.
    if isinstance(date, datetime.date):
        return date.strftime(date_format)
    return _UNKNOWN_DATETIME_BUCKET


def append_partition_key_to_table(
    table: pa.Table,
    partition_count: Optional[int],
    partition_size: Optional[int],
    partition_keys: list[str],
    partition_mode: PartitionMode | None,
    partition_format: PartitionFormat | None,
    logger: FilteringBoundLogger,
) -> None | tuple[pa.Table, PartitionMode, PartitionFormat | None, list[str]]:
    """
    Partitions the pyarrow table via one of these methods:
    - md5: Hashes the primary keys into a fixed number of buckets, the least efficient method of partitioning
    - datetime: Uses a stable timestamp, such as a created_at field, to partition the rows
    - numerical: Uses a numerical primary key to bucket the rows by count
    - datetime_md5: Composite of the above two — a datetime bucket from the first key, split further into
      md5 sub-buckets over the remaining keys. Rescues a date-only table stuck at its finest datetime tier
      (a single day still over budget) while keeping date locality for incremental merges.
    """

    normalized_partition_keys = [normalize_column_name(key) for key in partition_keys]
    mode: PartitionMode | None = partition_mode

    if mode is None:
        # If the source returns a partition count, then we can bucket by md5
        if partition_count is not None:
            mode = "md5"

        # If there is only one primary key and it's a numerical ID, then bucket by the ID itself instead of hashing it
        is_partition_key_int = normalized_partition_keys[0] in table.column_names and pa.types.is_integer(
            table.field(normalized_partition_keys[0]).type
        )
        are_incrementing_ints = False
        if is_partition_key_int:
            partition_column = table.column(normalized_partition_keys[0])
            # check if the column has any non-null values before calculating min max
            if partition_column.null_count < table.num_rows:
                bounds: dict[str, int | None] = cast(dict[str, int | None], pc.min_max(partition_column).as_py())
                _min, _max = bounds["min"], bounds["max"]
                if _min is not None and _max is not None:
                    range_size = _max - _min + 1
                    are_incrementing_ints = table.num_rows / range_size >= 0.2

        if (
            partition_size is not None
            and len(normalized_partition_keys) == 1
            and is_partition_key_int
            and are_incrementing_ints
        ):
            mode = "numerical"
        # If the table has a created_at-ish timestamp, then we can partition by this
        elif any(column_name in table.column_names for column_name in PARTITION_DATETIME_COLUMN_NAMES):
            for column_name in PARTITION_DATETIME_COLUMN_NAMES:
                if (
                    column_name in table.column_names
                    and pa.types.is_timestamp(table.field(column_name).type)
                    and table.column(column_name).null_count != table.num_rows
                ):
                    mode = "datetime"
                    normalized_partition_keys = [column_name]

        if mode is None:
            logger.debug("append_partition_key_to_table: partitioning skipped, no supported partition mode available")
            return None
        else:
            logger.debug(f"append_partition_key_to_table: partitioning mode {mode} selected")

    # A persisted partition mode skips the detection block above, so the partition key column may be
    # absent from this batch — e.g. the source's schema drifted and stopped returning the field we
    # previously partitioned on. Reading a missing key per-row would raise a raw KeyError and fail
    # every sync; instead those rows fall back to a catch-all bucket (the bucket helpers read via
    # `row.get`). When the missing field is also the incremental field, the downstream
    # incremental-value check surfaces an actionable, non-retryable error.
    missing_partition_keys = [key for key in normalized_partition_keys if key not in table.column_names]
    if missing_partition_keys:
        logger.warning(
            f"append_partition_key_to_table: partition key(s) missing from incoming table, bucketing into fallback: {missing_partition_keys}"
        )

    # Only the datetime modes use a format; default it here so it's also reflected in the returned value.
    if mode in ("datetime", "datetime_md5") and partition_format is None:
        partition_format = "week"

    partition_array: list[str] = []

    for batch in table.to_batches():
        for row in batch.to_pylist():
            if mode == "md5":
                assert partition_count is not None, "append_partition_key_to_table: partition_count is None"
                partition_array.append(_md5_partition_bucket(row, normalized_partition_keys, partition_count))
            elif mode == "numerical":
                assert partition_size is not None, "append_partition_key_to_table: partition_size is None"
                key = normalized_partition_keys[0]
                key_value = row.get(key)

                if key_value is None:
                    partition_array.append(NULL_NUMERICAL_PARTITION)
                elif isinstance(key_value, int):
                    partition_array.append(str(key_value // partition_size))
                else:
                    # A persisted "numerical" mode can outlive the integer key column that
                    # justified it (e.g. the source's key column changed type mid-sync). Coerce
                    # numeric values back to int so rows keep their original bucket; anything that
                    # isn't integer-like lands in the null bucket instead of crashing the sync.
                    try:
                        coerced_key_value = int(key_value)
                    except (TypeError, ValueError):
                        partition_array.append(NULL_NUMERICAL_PARTITION)
                    else:
                        partition_array.append(str(coerced_key_value // partition_size))
            elif mode == "datetime":
                assert partition_format is not None
                partition_array.append(
                    _datetime_partition_bucket(row.get(normalized_partition_keys[0]), partition_format)
                )
            elif mode == "datetime_md5":
                assert partition_count is not None, "append_partition_key_to_table: partition_count is None"
                assert partition_format is not None
                # First key is the datetime bucket; the rest are the md5 sub-bucket keys (fall back to the
                # datetime key itself if it's the only key). The `_` separator is S3-path-safe and can't
                # collide with a strftime bucket (none contain `_`) or an md5 integer.
                date_key = normalized_partition_keys[0]
                md5_keys = normalized_partition_keys[1:] or [date_key]
                date_bucket = _datetime_partition_bucket(row.get(date_key), partition_format)
                sub_bucket = _md5_partition_bucket(row, md5_keys, partition_count)
                partition_array.append(f"{date_bucket}_{sub_bucket}")
            else:
                raise ValueError(f"Partition mode '{mode}' not supported")

    new_column = pa.array(partition_array, type=pa.string())

    return table.append_column(PARTITION_KEY, new_column), mode, partition_format, normalized_partition_keys
