from __future__ import annotations

import hashlib
import datetime
from typing import TYPE_CHECKING, Optional, cast

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

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES = 200 * 1024 * 1024  # 200 MB

PARTITION_DATETIME_COLUMN_NAMES = ["created_at", "inserted_at", "createdAt"]

# Bucket for rows whose numerical partition key is null — they can't be bucketed arithmetically.
NULL_NUMERICAL_PARTITION = "null"


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
    Partitions the pyarrow table via one of three methods:
    - md5: Hashes the primary keys into a fixed number of buckets, the least efficient method of partitioning
    - datetime: Uses a stable timestamp, such as a created_at field, to partition the rows
    - numerical: Uses a numerical primary key to bucket the rows by count
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
    # every sync; instead those rows fall back to a catch-all bucket (via `row.get`). When the missing
    # field is also the incremental field, the downstream incremental-value check surfaces an
    # actionable, non-retryable error.
    missing_partition_keys = [key for key in normalized_partition_keys if key not in table.column_names]
    if missing_partition_keys:
        logger.warning(
            f"append_partition_key_to_table: partition key(s) missing from incoming table, bucketing into fallback: {missing_partition_keys}"
        )

    partition_array: list[str] = []

    for batch in table.to_batches():
        for row in batch.to_pylist():
            if mode == "md5":
                assert partition_count is not None, "append_partition_key_to_table: partition_count is None"

                primary_key_values = [str(row.get(key)) for key in normalized_partition_keys]
                delimited_primary_key_value = "|".join(primary_key_values)

                # this hash has no security impact
                # nosemgrep: python.lang.security.insecure-hash-algorithms-md5.insecure-hash-algorithm-md5
                hash_value = int(hashlib.md5(delimited_primary_key_value.encode()).hexdigest(), 16)
                partition = hash_value % partition_count

                partition_array.append(str(partition))
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
                key = normalized_partition_keys[0]
                date = row.get(key)

                if partition_format is None:
                    partition_format = "week"

                if partition_format == "hour":
                    date_format = "%Y-%m-%dT%H"
                elif partition_format == "day":
                    date_format = "%Y-%m-%d"
                elif partition_format == "week":
                    date_format = "%G-w%V"
                elif partition_format == "month":
                    date_format = "%Y-%m"

                if isinstance(date, int):
                    date = datetime.datetime.fromtimestamp(date)
                    partition_array.append(date.strftime(date_format))
                elif isinstance(date, datetime.datetime):
                    partition_array.append(date.strftime(date_format))
                elif isinstance(date, datetime.date):
                    partition_array.append(date.strftime(date_format))
                elif isinstance(date, str) and date.strip():
                    try:
                        date = parser.parse(date)
                        partition_array.append(date.strftime(date_format))
                    except (ValueError, OverflowError):
                        # Non-date-like string (e.g. a UUID primary key) — treat as unknown date
                        partition_array.append("1970-01")
                elif isinstance(date, str):
                    # Empty string — treat as unknown date
                    partition_array.append("1970-01")
                else:
                    partition_array.append("1970-01")
            else:
                raise ValueError(f"Partition mode '{mode}' not supported")

    new_column = pa.array(partition_array, type=pa.string())
    logger.debug(f"append_partition_key_to_table: Partition key added with mode={mode}")

    return table.append_column(PARTITION_KEY, new_column), mode, partition_format, normalized_partition_keys
