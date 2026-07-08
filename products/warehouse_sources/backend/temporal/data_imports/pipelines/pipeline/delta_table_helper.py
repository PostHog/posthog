import json
import asyncio
from collections.abc import Callable, Sequence
from typing import Any, Literal, TypeVar

from django.conf import settings

import numpy as np
import pyarrow as pa
import deltalake as deltalake
import pyarrow.compute as pc
import posthoganalytics
import deltalake.exceptions
from dlt.common.libs.deltalake import ensure_delta_compatible_arrow_schema
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool
from posthog.utils import get_machine_id

from products.data_warehouse.backend.facade.api import aget_s3_client, ensure_bucket_exists
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import (
    conditional_lru_cache_async,
    normalize_column_name,
    pyarrow_schema_from_arrow_exportable,
)

# A pre-write defensive compact fires when EITHER threshold is exceeded.
#
# Calibrated against the production file-count distribution (delta merge stats across
# all teams): total files per table sit at p50≈60, p90≈470, p95≈850, with a long tail
# (p99≈12k → ~14s merges; an observed pathological case hit ~82k files → ~45s merges).
# Merge planning time tracks TOTAL files, not files-per-partition — delta still
# enumerates every file's metadata even when partition pruning skips reading them — so
# we gate on both:
#
# - files-per-partition: bounds per-partition fragmentation and rescues partitioned
#   (esp. md5) tables, where a merge touches every partition. 200 sits well above the
#   healthy steady state (compaction runs at the end of each successful sync) yet
#   triggers long before a table reaches the slow tail.
# - total files: a partition-count-independent backstop so a table with a high
#   partition_count can't accumulate tens of thousands of files (each adding to merge
#   planning time) while staying under the per-partition bar. 5,000 is above p95 (~850)
#   — so healthy tables never trip it — and well below the p99/pathological tail.
#
# Tune further once the admin fragmentation view gives per-customer distributions.
DEFAULT_COMPACT_FILES_PER_PARTITION_THRESHOLD = 200
DEFAULT_COMPACT_TOTAL_FILES_THRESHOLD = 5000

T = TypeVar("T")

# delta-rs surfaces momentary object-storage hiccups (S3 LIST/GET flakes, TCP resets) as
# DeltaError / OSError whose message carries a recognisable marker. They clear on retry or by
# the next sync, so the delta-maintenance and corruption-check paths must neither fail the sync
# nor mint a fresh error-tracking issue via `capture_exception` over one — they retry, then
# downgrade to a warning. Matched case-insensitively against the exception message.
_TRANSIENT_OBJECT_STORAGE_ERROR_MARKERS = (
    "generic s3 error",
    "error getting list response body",
    "error decoding response body",
    "connection reset by peer",
    "connection closed",
    "broken pipe",
    "os error 104",
    "timed out",
    "operation timed out",
    "request timeout",
    "dispatch task is gone",
    "connection refused",
)


def is_transient_object_storage_error(e: BaseException) -> bool:
    """True for a momentary S3/network flake raised by delta-rs (LIST/GET body errors, TCP resets).

    These bubble up from the `is_deltatable` existence check and the vacuum/compact LIST+delete as
    DeltaError / OSError with a recognisable message. They are transient, so callers retry them and,
    if they persist, downgrade to a warning rather than capturing a one-off error-tracking issue.
    """
    args = getattr(e, "args", None) or ()
    message = " ".join(str(arg) for arg in args) or str(e)
    message = message.lower()
    return any(marker in message for marker in _TRANSIENT_OBJECT_STORAGE_ERROR_MARKERS)


async def _run_with_transient_retry(
    fn: Callable[[], T],
    *,
    logger: FilteringBoundLogger,
    op_name: str,
    attempts: int = 3,
    base_backoff_seconds: float = 0.5,
) -> T:
    """Run a blocking delta-rs call in a thread, retrying only on transient object-storage errors.

    Non-transient errors (real corruption, schema mismatches, auth failures) propagate immediately —
    only the momentary S3/network flakes in `_TRANSIENT_OBJECT_STORAGE_ERROR_MARKERS` are retried,
    with a short linear backoff. The final failure re-raises so the caller's guard can decide.
    """
    for attempt in range(1, attempts + 1):
        try:
            return await asyncio.to_thread(fn)
        except Exception as e:
            if attempt >= attempts or not is_transient_object_storage_error(e):
                raise
            await logger.adebug(
                f"{op_name}: transient object-storage error (attempt {attempt}/{attempts}), retrying: {e}"
            )
            await asyncio.sleep(base_backoff_seconds * attempt)
    raise AssertionError("unreachable")  # pragma: no cover - loop either returns or raises


def _write_deltalake(
    table_or_uri: str | deltalake.DeltaTable,
    table_data: pa.Table,
    partition_by: str | None,
    mode: Literal["error", "append", "overwrite", "ignore"],
    schema_mode: Literal["merge", "overwrite"] | None,
    commit_properties: deltalake.CommitProperties | None = None,
) -> None:
    deltalake.write_deltalake(
        table_or_uri=table_or_uri,
        data=table_data,
        partition_by=partition_by,
        mode=mode,
        schema_mode=schema_mode,
        commit_properties=commit_properties,
    )


def _realign_decimal_buffers(table: pa.Table) -> pa.Table:
    """Re-materialize any Decimal128/256 column whose values buffer isn't 16-byte aligned.

    delta-rs (arrow-rs) aborts the entire worker — not a catchable Python exception,
    an `abort()` at the `extern "C"` boundary that can't unwind — when it's handed a
    decimal values buffer aligned to 8 bytes instead of the 16 that Rust's i128 requires.
    The misalignment arrives across the Arrow C Data Interface, which only recommends
    8-byte alignment. We funnel every Delta write/merge through here so a single guard
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
            new_columns[field.name] = pa.chunked_array([pa.concat_arrays(column.chunks)], type=field.type)
            realigned = True
        else:
            new_columns[field.name] = column

    if not realigned:
        return table

    return pa.table(new_columns, schema=table.schema)


def _first_per_pk_table(
    pa_table: pa.Table, pk_columns: list[str], keep: Literal["first", "last"] = "first"
) -> pa.Table:
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
    aggregate = "min" if keep == "first" else "max"

    # 1. Add a row-position column: [0, 1, 2, ..., n-1]
    indexed = pa_table.append_column(idx_col_name, pa.array(range(pa_table.num_rows), type=pa.int64()))

    # 2. Group by PK, keeping only one position per PK
    grouped = indexed.group_by(pk_columns).aggregate([(idx_col_name, aggregate)])

    # 3. Sort those positions ascending so the output mirrors the input row order
    kept_indices = np.sort(grouped.column(f"{idx_col_name}_{aggregate}").to_numpy())

    # 4. Materialize the rows at those positions from the original table
    return pa_table.take(kept_indices)


class DeltaTableHelper:
    _resource_name: str
    _job: ExternalDataJob
    _logger: FilteringBoundLogger
    _is_first_sync: bool

    def __init__(
        self, resource_name: str, job: ExternalDataJob, logger: FilteringBoundLogger, is_first_sync: bool = False
    ) -> None:
        self._resource_name = resource_name
        self._job = job
        self._logger = logger
        self._is_first_sync = is_first_sync

    @property
    def is_first_sync(self) -> bool:
        return self._is_first_sync

    def _get_credentials(self):
        if settings.USE_LOCAL_SETUP:
            if (
                not settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY
                or not settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET
                or not settings.DATAWAREHOUSE_LOCAL_BUCKET_REGION
            ):
                raise KeyError(
                    "Missing env vars for data warehouse. Required vars: DATAWAREHOUSE_LOCAL_ACCESS_KEY, DATAWAREHOUSE_LOCAL_ACCESS_SECRET, DATAWAREHOUSE_LOCAL_BUCKET_REGION"
                )

            ensure_bucket_exists(
                settings.BUCKET_URL,
                settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
                settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
                settings.OBJECT_STORAGE_ENDPOINT,
            )

            return {
                "aws_access_key_id": settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
                "aws_secret_access_key": settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
                "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
                "region_name": settings.DATAWAREHOUSE_LOCAL_BUCKET_REGION,
                "AWS_DEFAULT_REGION": settings.DATAWAREHOUSE_LOCAL_BUCKET_REGION,
                "AWS_ALLOW_HTTP": "true",
                "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
            }

        return {
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    async def _get_delta_table_uri(self) -> str:
        normalized_resource_name = NamingConvention.normalize_identifier(self._resource_name)
        folder_path = await database_sync_to_async_pool(self._job.folder_path)()
        return f"{settings.BUCKET_URL}/{folder_path}/{normalized_resource_name}"

    async def get_table_uri(self) -> str:
        """Public accessor for the live Delta table S3 URI (used by the in-place repartitioner)."""
        return await self._get_delta_table_uri()

    def get_storage_options(self) -> dict[str, str]:
        """Public accessor for the delta-rs storage options (used by the in-place repartitioner)."""
        return self._get_credentials()

    async def _evolve_delta_schema(self, schema: pa.Schema) -> deltalake.DeltaTable:
        delta_table = await self.get_delta_table()
        if delta_table is None:
            raise Exception("Deltalake table not found")

        delta_table_schema = pyarrow_schema_from_arrow_exportable(delta_table.schema())

        new_fields = [
            deltalake.Field.from_arrow(field)
            for field in ensure_delta_compatible_arrow_schema(schema)
            if field.name not in delta_table_schema.names
        ]
        if new_fields:
            await asyncio.to_thread(delta_table.alter.add_columns, new_fields)

        return delta_table

    @conditional_lru_cache_async(maxsize=1, condition=lambda result: result is not None)
    async def get_delta_table(self) -> deltalake.DeltaTable | None:
        delta_uri = await self._get_delta_table_uri()
        storage_options = self._get_credentials()

        is_delta = await _run_with_transient_retry(
            lambda: deltalake.DeltaTable.is_deltatable(table_uri=delta_uri, storage_options=storage_options),
            logger=self._logger,
            op_name="get_delta_table.is_deltatable",
        )
        if is_delta:
            try:
                return await _run_with_transient_retry(
                    lambda: deltalake.DeltaTable(table_uri=delta_uri, storage_options=storage_options),
                    logger=self._logger,
                    op_name="get_delta_table.open",
                )
            except Exception as e:
                # A transient S3/network flake here is not a bugged table — let it propagate so the
                # activity retries, without minting an error-tracking issue for a momentary hiccup.
                if is_transient_object_storage_error(e):
                    raise
                # Temp fix for bugged tables
                capture_exception(e)
                if "parse decimal overflow" in "".join(e.args):
                    async with aget_s3_client() as s3:
                        await s3._rm(delta_uri, recursive=True)
                else:
                    raise

        self._is_first_sync = True

        return None

    async def is_table_corrupted(self) -> bool:
        """True when the Delta log exists but the table can't be opened (DeltaError / FileNotFoundError).

        The signature of a `_delta_log` left inconsistent by an interrupted repartition swap or an
        OOM-crashed merge — after which every sync fails to open the table and loops. Non-destructive:
        only attempts an open (bypassing the get_delta_table cache). A table that simply doesn't exist is
        not corrupt; an unknown open error is not classified as corrupt, and a transient S3/network flake
        (which delta-rs also raises as a DeltaError) never triggers a destructive revive.
        """
        delta_uri = await self._get_delta_table_uri()
        storage_options = self._get_credentials()

        is_delta = await _run_with_transient_retry(
            lambda: deltalake.DeltaTable.is_deltatable(table_uri=delta_uri, storage_options=storage_options),
            logger=self._logger,
            op_name="is_table_corrupted.is_deltatable",
        )
        if not is_delta:
            return False

        try:
            await _run_with_transient_retry(
                lambda: deltalake.DeltaTable(table_uri=delta_uri, storage_options=storage_options),
                logger=self._logger,
                op_name="is_table_corrupted.open",
            )
            return False
        except (deltalake.exceptions.DeltaError, FileNotFoundError) as e:
            # A transient S3/network error is raised as a DeltaError too — do not classify it as
            # corruption, or a momentary flake would trigger a destructive reset + rebuild.
            if is_transient_object_storage_error(e):
                return False
            return True
        except Exception:
            return False

    async def reset_table(self):
        delta_uri = await self._get_delta_table_uri()

        async with aget_s3_client() as s3:
            try:
                await s3._rm(delta_uri, recursive=True)
            except FileNotFoundError:
                pass

        self.get_delta_table.cache_clear()

        await self._logger.adebug("reset_table: _is_first_sync=True")
        self._is_first_sync = True

    async def get_file_uris(self) -> list[str]:
        delta_table = await self.get_delta_table()
        if delta_table is None:
            return []

        return await asyncio.to_thread(delta_table.file_uris)

    async def _dedupe_incremental_batch(
        self, data: pa.Table, primary_keys: Sequence[Any], use_partitioning: bool
    ) -> pa.Table:
        """Drop all but the last occurrence of each PK (+ partition) tuple in a batch."""
        dedupe_keys = [n for x in primary_keys if (n := normalize_column_name(x)) in data.column_names]
        if not dedupe_keys:
            return data
        if use_partitioning:
            dedupe_keys.append(PARTITION_KEY)

        deduped = _first_per_pk_table(data, dedupe_keys, keep="last")
        dropped = data.num_rows - deduped.num_rows
        if dropped > 0:
            await self._logger.awarning(
                f"write_to_deltalake: dropped {dropped} duplicate primary-key rows "
                f"(keys={dedupe_keys}) from a batch of {data.num_rows} before writing"
            )
        return deduped

    async def write_to_deltalake(
        self,
        data: pa.Table,
        write_type: Literal["incremental", "full_refresh", "append"],
        should_overwrite_table: bool,
        primary_keys: Sequence[Any] | None,
        progress_callback: Callable[[], None] | None = None,
        commit_metadata: dict[str, str] | None = None,
    ) -> deltalake.DeltaTable:
        # Guard against delta-rs aborting the worker on misaligned decimal buffers (see
        # _realign_decimal_buffers). Sub-tables derived below via filter()/take() are
        # freshly allocated by pyarrow and so inherit safe alignment.
        data = _realign_decimal_buffers(data)

        delta_table = await self.get_delta_table()

        if delta_table:
            delta_table = await self._evolve_delta_schema(data.schema)

        await self._logger.adebug(
            f"write_to_deltalake: _is_first_sync = {self._is_first_sync}. should_overwrite_table = {should_overwrite_table}"
        )

        use_partitioning = False
        if PARTITION_KEY in data.column_names:
            use_partitioning = True
            await self._logger.adebug(f"Using partitioning on {PARTITION_KEY}")

        # The column can exist without the table being partitioned by it; defer to the
        # table's real partition_columns or delta-rs rejects the write as a mismatch.
        if use_partitioning and delta_table is not None:
            existing_partition_columns = getattr(delta_table.metadata(), "partition_columns", None) or []
            if PARTITION_KEY not in existing_partition_columns:
                use_partitioning = False
                await self._logger.adebug(
                    f"Existing table is not partitioned by {PARTITION_KEY}; skipping partitioning to match its layout"
                )

        commit_properties: deltalake.CommitProperties | None = (
            deltalake.CommitProperties(custom_metadata=commit_metadata) if commit_metadata else None
        )

        if write_type == "incremental" and primary_keys:
            # Sources can emit the same key twice in one batch (re-listed parents, retried
            # pages, genuinely non-unique upstream ids). The merge treats PK (+ partition)
            # as row identity, and duplicates on the source side either error the merge or
            # get double-inserted by `when_not_matched_insert_all` — after which every later
            # merge multi-matches those rows and blows up. Keep only the last occurrence.
            data = await self._dedupe_incremental_batch(data, primary_keys, use_partitioning)

        if write_type == "incremental" and delta_table is not None and not self._is_first_sync:
            if not primary_keys or len(primary_keys) == 0:
                raise Exception("Primary key required for incremental syncs")

            existing_delta_table = delta_table

            await self._logger.adebug(f"write_to_deltalake: merging...")

            # Normalize keys and check the keys actually exist in the dataset
            py_table_column_names = data.column_names
            normalized_primary_keys: list[str] = []
            for x in primary_keys:
                n = normalize_column_name(x)
                if n in py_table_column_names:
                    normalized_primary_keys.append(n)

            predicate_ops = [f"source.{c} = target.{c}" for c in normalized_primary_keys]
            if use_partitioning:
                predicate_ops.append(f"source.{PARTITION_KEY} = target.{PARTITION_KEY}")

                # Group the table by the partition key and merge multiple times with streamed_exec=True for optimised merging
                unique_partitions = list(pc.unique(data[PARTITION_KEY]))  # type: ignore

                await self._logger.adebug(f"Running {len(unique_partitions)} optimised merges")

                # Only tag the FINAL partition merge with `commit_properties`. Intermediate
                # merges must remain untagged so a crash mid-loop doesn't leave behind a
                # tagged commit that would cause `has_batch_been_committed` to skip the
                # remaining partitions on Kafka redelivery (which would lose data).
                last_partition_index = len(unique_partitions) - 1
                for i, partition in enumerate(unique_partitions):
                    partition_predicate_ops = predicate_ops.copy()
                    partition_predicate_ops.append(f"target.{PARTITION_KEY} = '{partition}'")
                    predicate = " AND ".join(partition_predicate_ops)

                    filtered_table = data.filter(pc.equal(data[PARTITION_KEY], partition))

                    await self._logger.adebug(f"Merging partition={partition} with predicate={predicate}")

                    merge_commit_properties = commit_properties if i == last_partition_index else None

                    def _do_merge(
                        filtered_table: pa.Table,
                        predicate: str,
                        merge_commit_properties: deltalake.CommitProperties | None,
                    ):
                        return (
                            existing_delta_table.merge(
                                source=filtered_table,
                                source_alias="source",
                                target_alias="target",
                                predicate=predicate,
                                streamed_exec=True,
                                commit_properties=merge_commit_properties,
                            )
                            .when_matched_update_all()
                            .when_not_matched_insert_all()
                            .execute()
                        )

                    merge_stats = await asyncio.to_thread(_do_merge, filtered_table, predicate, merge_commit_properties)

                    await self._logger.adebug(f"Delta Merge Stats: {json.dumps(merge_stats)}")

                    if progress_callback:
                        progress_callback()
            else:
                # Single merge call → safe to tag directly; this is the terminal commit.
                def _do_merge_unpartitioned(data: pa.Table, predicate_ops: list[str]):
                    return (
                        existing_delta_table.merge(
                            source=data,
                            source_alias="source",
                            target_alias="target",
                            predicate=" AND ".join(predicate_ops),
                            streamed_exec=False,
                            commit_properties=commit_properties,
                        )
                        .when_matched_update_all()
                        .when_not_matched_insert_all()
                        .execute()
                    )

                merge_stats = await asyncio.to_thread(_do_merge_unpartitioned, data, predicate_ops)
                await self._logger.adebug(f"Delta Merge Stats: {json.dumps(merge_stats)}")
        elif (
            write_type == "full_refresh"
            or (write_type == "incremental" and delta_table is None)
            or (write_type == "incremental" and self._is_first_sync)
        ):
            mode: Literal["error", "append", "overwrite", "ignore"] = "append"
            schema_mode: Literal["merge", "overwrite"] | None = "merge"
            if should_overwrite_table or delta_table is None:
                mode = "overwrite"
                schema_mode = "overwrite"

            await self._logger.adebug(f"write_to_deltalake: mode = {mode}")

            if delta_table is None:
                storage_options = self._get_credentials()
                delta_uri = await self._get_delta_table_uri()
                delta_table = await asyncio.to_thread(
                    deltalake.DeltaTable.create,
                    table_uri=delta_uri,
                    schema=data.schema,
                    storage_options=storage_options,
                    partition_by=PARTITION_KEY if use_partitioning else None,
                )

            try:
                await asyncio.to_thread(
                    _write_deltalake,
                    delta_table,
                    data,
                    partition_by=PARTITION_KEY if use_partitioning else None,
                    mode=mode,
                    schema_mode=schema_mode,
                    commit_properties=commit_properties,
                )
            except deltalake.exceptions.SchemaMismatchError as e:
                await self._logger.adebug("SchemaMismatchError: attempting to overwrite schema instead", exc_info=e)
                capture_exception(e)

                await asyncio.to_thread(
                    _write_deltalake,
                    delta_table,
                    data,
                    partition_by=None,
                    mode=mode,
                    schema_mode="overwrite",
                    commit_properties=commit_properties,
                )
        elif write_type == "append":
            if delta_table is None:
                storage_options = self._get_credentials()
                delta_uri = await self._get_delta_table_uri()
                delta_table = await asyncio.to_thread(
                    deltalake.DeltaTable.create,
                    table_uri=delta_uri,
                    schema=data.schema,
                    storage_options=storage_options,
                    partition_by=PARTITION_KEY if use_partitioning else None,
                )

            await self._logger.adebug(f"write_to_deltalake: write_type = append")

            await asyncio.to_thread(
                _write_deltalake,
                delta_table,
                data,
                partition_by=PARTITION_KEY if use_partitioning else None,
                mode="append",
                schema_mode="merge",
                commit_properties=commit_properties,
            )

        delta_table = await self.get_delta_table()
        assert delta_table is not None

        return delta_table

    async def write_scd2_to_deltalake(
        self,
        data: pa.Table,
        primary_keys: Sequence[Any],
        commit_metadata: dict[str, str] | None = None,
    ) -> deltalake.DeltaTable:
        """Write CDC SCD Type 2 data: close existing current rows, then append new rows.

        For each PK that appears in `data`:
        1. Find the existing row in the target with matching PK and valid_to IS NULL
           (the current row) and update its valid_to to the earliest valid_from of the
           new events for that PK.
        2. Append all rows from `data` as new history entries.

        `data` is expected to already have valid_from / valid_to columns as produced
        by batcher.build_scd2_table().
        """
        # See write_to_deltalake / _realign_decimal_buffers. The close-existing merge uses
        # _first_per_pk_table(data), whose take() output is freshly allocated, so realigning
        # `data` here covers both the close and the append.
        data = _realign_decimal_buffers(data)

        delta_table = await self.get_delta_table()

        if delta_table:
            delta_table = await self._evolve_delta_schema(data.schema)

        commit_properties: deltalake.CommitProperties | None = (
            deltalake.CommitProperties(custom_metadata=commit_metadata) if commit_metadata else None
        )

        # Step 1: Close existing current rows for PKs in this batch
        if delta_table is not None and primary_keys and "valid_from" in data.column_names:
            existing_delta_table = delta_table
            py_column_names = data.column_names
            normalized_pks: list[str] = []
            for x in primary_keys:
                n = normalize_column_name(x)
                if n in py_column_names:
                    normalized_pks.append(n)

            if normalized_pks:
                # Use only the first row per PK to avoid ambiguous multi-match merge
                first_per_pk = _first_per_pk_table(data, normalized_pks)

                predicate_parts = [f"source.{col} = target.{col}" for col in normalized_pks]
                predicate_parts.append("target.valid_to IS NULL")
                predicate = " AND ".join(predicate_parts)

                # NOTE: do NOT tag this intermediate merge with `commit_properties`. SCD2 is a
                # two-step write (close-existing then append-new); if we tagged step 1 with the
                # same (run_uuid, batch_index) and the process crashed before step 2, Kafka
                # redelivery would see the tagged commit, treat the batch as already done, and
                # silently skip the append → data loss. Tag only the terminal commit (step 2).
                def _do_scd2_close(first_per_pk: pa.Table, predicate: str) -> dict:
                    return (
                        existing_delta_table.merge(
                            source=first_per_pk,
                            source_alias="source",
                            target_alias="target",
                            predicate=predicate,
                            streamed_exec=False,
                        )
                        .when_matched_update(updates={"valid_to": "source.valid_from"})
                        .execute()
                    )

                close_stats = await asyncio.to_thread(_do_scd2_close, first_per_pk, predicate)
                await self._logger.adebug(f"SCD2 close stats: {json.dumps(close_stats)}")

        # Step 2: Append all new rows
        if delta_table is None:
            storage_options = self._get_credentials()
            delta_uri = await self._get_delta_table_uri()
            delta_table = await asyncio.to_thread(
                deltalake.DeltaTable.create,
                table_uri=delta_uri,
                schema=data.schema,
                storage_options=storage_options,
            )

        await asyncio.to_thread(
            deltalake.write_deltalake,
            table_or_uri=delta_table,
            data=data,
            mode="append",
            schema_mode="merge",
            commit_properties=commit_properties,
        )

        delta_table = await self.get_delta_table()
        assert delta_table is not None
        return delta_table

    async def has_commit_with_metadata(self, match: dict[str, str], *, scan_limit: int = 50) -> bool:
        """Check whether any recent delta commit has custom metadata matching all entries in `match`.

        Used to detect that a given (run_uuid, batch_index) has already been written
        even when a faster external dedup cache (e.g. Redis) is missing the marker —
        the canonical case is a writer crash between a successful `write_to_deltalake`
        and the subsequent cache update.

        delta-rs `history()` returns commits where `CommitProperties.custom_metadata`
        entries are flattened directly into the commit dict alongside `operation`,
        `timestamp`, etc. Older versions nested them under a `userMetadata` key, so
        we accept both layouts for forward compatibility.
        """
        delta_table = await self.get_delta_table()
        if delta_table is None:
            return False

        history = await asyncio.to_thread(delta_table.history, limit=scan_limit)

        for commit in history:
            if self._commit_matches(commit, match):
                return True

        return False

    @staticmethod
    def _commit_matches(commit: dict[str, Any], match: dict[str, str]) -> bool:
        """Return True iff every (k, v) in `match` is present in this commit's metadata.

        Handles both the flat layout (delta-rs 1.x inlines custom_metadata onto the
        top-level commit dict) and a nested `userMetadata` key (older/other layouts).
        """
        if all(commit.get(k) == v for k, v in match.items()):
            return True

        raw = commit.get("userMetadata")
        if raw is None:
            return False

        if isinstance(raw, str):
            try:
                nested = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                return False
        elif isinstance(raw, dict):
            nested = raw
        else:
            return False

        return all(nested.get(k) == v for k, v in match.items())

    async def has_batch_been_committed(self, run_uuid: str, batch_index: int) -> bool:
        """Check whether a specific (run_uuid, batch_index) has already been committed to delta.

        Thin wrapper around `has_commit_with_metadata` so callers don't need to know
        the metadata schema used for idempotency tagging.
        """
        return await self.has_commit_with_metadata({"run_uuid": run_uuid, "batch_index": str(batch_index)})

    async def vacuum_table(self) -> None:
        table = await self.get_delta_table()
        if table is None:
            raise Exception("Deltatable not found")

        await self._logger.adebug("Vacuuming table...")
        vacuum_stats = await _run_with_transient_retry(
            lambda: table.vacuum(retention_hours=24, enforce_retention_duration=False, dry_run=False),
            logger=self._logger,
            op_name="vacuum_table",
        )
        await self._logger.adebug(json.dumps(vacuum_stats))

    async def compact_table(self) -> None:
        table = await self.get_delta_table()
        if table is None:
            raise Exception("Deltatable not found")

        await self._logger.adebug("Compacting table...")
        compact_stats = await _run_with_transient_retry(
            lambda: table.optimize.compact(),
            logger=self._logger,
            op_name="compact_table",
        )
        await self._logger.adebug(json.dumps(compact_stats))

        await self.vacuum_table()
        await self._logger.adebug("Compacting and vacuuming complete")

    async def vacuum_if_stale(self, last_vacuum_version: int | None, commit_threshold: int) -> int | None:
        """Vacuum tombstoned files once enough commits have accrued since the last vacuum.

        Decoupled from merge success (called pre-write) so a table that OOMs its merge every run still
        gets cleaned — the post-load compaction never runs for it, which is how tables reach ~99% dead
        files. Vacuum only deletes dead files (an S3 LIST + delete), so unlike `compact_table`'s
        `optimize.compact` (which rewrites partitions) it is memory-safe even on an oversized table.

        Uses the delta version (commit count) as a cheap proxy for tombstone accumulation — no S3 LIST to
        decide. Returns the current version to persist as the new watermark when it vacuumed, or on first
        encounter (seeding the watermark without vacuuming, to avoid a synchronized vacuum wave on deploy);
        None when nothing changed.
        """
        table = await self.get_delta_table()
        if table is None:
            return None

        version = await asyncio.to_thread(table.version)
        if last_vacuum_version is None:
            # First encounter: seed the watermark without vacuuming so existing tables clean up gradually
            # over the next `commit_threshold` commits rather than all vacuuming at once on deploy.
            return version

        commits_since = version - last_vacuum_version
        if commits_since < commit_threshold:
            await self._logger.adebug(
                f"vacuum_if_stale: skipping, {commits_since} commits since last vacuum (< {commit_threshold})"
            )
            return None

        await self._logger.ainfo(
            f"vacuum_if_stale: {commits_since} commits since last vacuum (>= {commit_threshold}), vacuuming"
        )
        await self.vacuum_table()
        try:
            # Observability for the maintenance path — how often tables vacuum and how much log churn
            # accrued between vacuums. Best-effort: telemetry must never break the sync.
            posthoganalytics.capture(
                distinct_id=get_machine_id(),
                event="warehouse_delta_vacuumed",
                properties={
                    "team_id": self._job.team_id,
                    "schema_id": str(self._job.schema_id),
                    "source_id": str(self._job.pipeline_id),
                    "resource_name": self._resource_name,
                    "commits_since_last_vacuum": commits_since,
                    "delta_version": version,
                },
            )
        except Exception as e:
            capture_exception(e)
        return version

    async def compact_if_fragmented(
        self,
        partition_count: int | None,
        threshold: int = DEFAULT_COMPACT_FILES_PER_PARTITION_THRESHOLD,
        total_threshold: int = DEFAULT_COMPACT_TOTAL_FILES_THRESHOLD,
    ) -> bool:
        """Run compact + vacuum if the table is fragmented past either threshold.

        Fragmented = files-per-partition > `threshold` OR total files > `total_threshold`.
        The total-files backstop matters because delta enumerates every file's metadata
        during a merge even when partition pruning skips reading them, so merge planning
        time tracks total files — a high partition_count must not let a table accumulate
        tens of thousands of files while staying under the per-partition bar.

        Returns True if compaction ran, False if it was skipped. Cheap when the table is
        healthy: one S3 LIST via `get_file_uris`. Intended for pre-write defensive cleanup
        so a sync that arrived at a fragmented state (e.g. an earlier attempt that failed
        before reaching `_post_run_operations`) cleans up before adding to the pile.
        """
        table = await self.get_delta_table()
        if table is None:
            return False

        file_uris = await self.get_file_uris()
        total_files = len(file_uris)
        # Treat unpartitioned tables as one "partition" for the threshold math.
        effective_partitions = max(partition_count or 1, 1)
        files_per_partition = total_files / effective_partitions

        fragmented = files_per_partition > threshold or total_files > total_threshold
        stats = (
            f"total_files={total_files}, partitions={effective_partitions}, "
            f"files_per_partition={files_per_partition:.1f}, threshold={threshold}, "
            f"total_threshold={total_threshold}"
        )
        if not fragmented:
            await self._logger.adebug(f"compact_if_fragmented: skipping ({stats})")
            return False

        await self._logger.ainfo(f"compact_if_fragmented: triggering compact ({stats})")
        await self.compact_table()
        return True

    async def run_maintenance(
        self,
        partition_count: int | None,
        last_vacuum_version: int | None,
        commit_threshold: int,
    ) -> int | None:
        """Single pre-write maintenance entry point: compact if fragmented, else vacuum on commit cadence.

        The two triggers are orthogonal — fragmentation (active file count) vs. commit cadence (tombstone
        accrual) — but they share one outcome, the vacuum watermark. `compact_if_fragmented` already
        vacuums as part of compaction, so when it runs it supersedes the cadence vacuum (no double vacuum
        in one run) and the watermark advances to the post-compaction version. When nothing was fragmented,
        fall through to `vacuum_if_stale`. Returns the single delta version to persist as the new
        `last_vacuum_version` watermark, or None when nothing changed; the caller is the sole writer of
        the watermark so it lives in exactly one place.
        """
        compacted = await self.compact_if_fragmented(partition_count=partition_count)
        if compacted:
            table = await self.get_delta_table()
            if table is None:
                return None
            # Compaction (which vacuumed) added a commit, advancing the version; reset the cadence
            # watermark to it so the next vacuum is measured from this cleanup, not the old baseline.
            return await asyncio.to_thread(table.version)
        return await self.vacuum_if_stale(last_vacuum_version, commit_threshold)
