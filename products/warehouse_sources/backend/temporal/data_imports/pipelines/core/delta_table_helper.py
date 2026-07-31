import json
import time
import asyncio
import contextlib
from collections.abc import Callable, Sequence
from typing import Any, Literal

from django.conf import settings

import pyarrow as pa
import deltalake as deltalake
import pyarrow.compute as pc
import deltalake.exceptions
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool

from products.data_warehouse.backend.facade.api import aget_s3_client, ensure_bucket_exists
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    align_incoming_decimals_to_delta,
    conditional_lru_cache_async,
    first_per_pk_table,
    normalize_column_name,
    realign_decimal_buffers,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.consts import PARTITION_KEY
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import (
    is_transient_object_store_error,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.evolution import evolve_delta_schema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.ops import (
    delta_merge_spill_kwargs,
    execute_with_conflict_retry,
)

# _purge_s3_prefix is idempotent (every step is existence-gated), so retrying it whole after a brief
# backoff is as safe as retrying a single failed call, and simpler.
_PURGE_S3_PREFIX_MAX_ATTEMPTS = 4


async def _purge_s3_prefix(s3: Any, uri: str) -> None:
    """Delete every object under `uri`, retrying on transient S3 SlowDown throttling.

    Bulk-listing and bulk-deleting a table's worth of objects can trip S3's `SlowDown` response
    under enough request volume; retry the whole (idempotent) purge with backoff before giving up.
    """
    attempt = 0
    while True:
        try:
            await _purge_s3_prefix_once(s3, uri)
            return
        except OSError as e:
            attempt += 1
            if attempt >= _PURGE_S3_PREFIX_MAX_ATTEMPTS or not is_transient_object_store_error(e):
                raise
            await asyncio.sleep(2**attempt)


async def _purge_s3_prefix_once(s3: Any, uri: str) -> None:
    """Delete every object under `uri`, resilient to S3 recursive-delete gaps.

    A lone `_rm(uri, recursive=True)` can leave objects behind on S3-compatible stores (directory
    markers, and — mid-write — partial `_delta_log` files). Strays are corrupting: a later
    `write_deltalake` append onto a half-cleared temp then sees a malformed table ("No table metadata
    or protocol found in delta log"), and a swap copy that lands on top of undeleted live files leaves
    a merged `_delta_log` whose row count is wrong ("swap verification failed: live > expected").
    Enumerate and delete explicitly first, then a best-effort recursive sweep.

    The dircache is dropped first: delta-rs writes through its own Rust object store, so s3fs's
    listing cache never learns about those files — a cached listing would leave exactly them behind.
    """
    s3.invalidate_cache()
    if not await s3._exists(uri):
        return
    files = await s3._find(uri)
    if files:
        await s3._rm([f"s3://{f.lstrip('/')}" for f in files])
    if await s3._exists(uri):
        await s3._rm(uri, recursive=True)


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


def _merge_predicate_ops(normalized_primary_keys: list[str]) -> list[str]:
    """Per-key merge match conditions, using NULL-safe equality.

    delta-rs matches source↔target with plain `source.c = target.c`, which is NULL-*un*safe:
    `NULL = NULL` evaluates to NULL (not true). Composite keys with nullable columns — e.g. the
    GoogleAds report resources keyed on `segments.ad_network_type` / `segments.click_type` /
    `segments.device`, which are frequently NULL — therefore never match their existing target row,
    so `when_not_matched_insert_all` re-inserts them on *every* incremental sync and the table
    silently accumulates a duplicate per NULL-keyed row. `IS NOT DISTINCT FROM` treats NULL == NULL,
    matching the source dedup (`first_per_pk_table` groups NULLs together) and stopping the drift.

    Each term is parenthesised: delta-rs's predicate parser (1.6.1) mis-associates a bare
    `a IS NOT DISTINCT FROM b AND c IS NOT DISTINCT FROM d` (it groups `b AND c`), so the parens are
    required for it to plan.
    """
    return [f"(source.{c} IS NOT DISTINCT FROM target.{c})" for c in normalized_primary_keys]


def _deltalite_write_stats(stats: Any) -> dict[str, int | float | str | bool]:
    """Flatten a deltalite ``UpsertStats`` into scalar log fields for structured, parseable output.

    Enumerates the object's public scalar attributes (the pyo3 ``#[pyo3(get)]`` getters — version,
    partitions_touched, files_added/removed/carried_over/probed, rows_updated/inserted/copied,
    source_rows, null_pk_rows, …) rather than a fixed list, so fields added crate-side later (e.g.
    per-phase timings) surface automatically. Best-effort — a stats change must never break the write.
    """
    fields: dict[str, int | float | str | bool] = {}
    for name in dir(stats):
        if name.startswith("_"):
            continue
        try:
            value = getattr(stats, name)
        except Exception:  # noqa: BLE001 - a flaky getter must not break logging a committed write
            continue
        if isinstance(value, bool | int | float | str):
            fields[name] = value
    return fields


def delta_storage_options() -> dict[str, str]:
    """delta-rs storage options for the data-warehouse bucket, independent of any import job — so a
    read path (e.g. the person-property backfill) can open a Delta table without constructing a full
    ``DeltaTableHelper`` (which carries caching, first-sync mutation, and corruption-repair)."""
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

        options = {
            "aws_access_key_id": settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
            "aws_secret_access_key": settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "region_name": settings.DATAWAREHOUSE_LOCAL_BUCKET_REGION,
            "AWS_DEFAULT_REGION": settings.DATAWAREHOUSE_LOCAL_BUCKET_REGION,
            "AWS_ALLOW_HTTP": "true",
        }
    else:
        options = {}

    # Conditional puts make a clashing concurrent commit fail loudly instead of
    # clobbering _delta_log; set explicitly so a library default change can't undo it.
    options["conditional_put"] = "etag"
    if settings.DATA_WAREHOUSE_DELTA_S3_ALLOW_UNSAFE_RENAME:
        options["AWS_S3_ALLOW_UNSAFE_RENAME"] = "true"
    return options


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

    @property
    def job(self) -> ExternalDataJob:
        return self._job

    @property
    def resource_name(self) -> str:
        return self._resource_name

    @property
    def logger(self) -> FilteringBoundLogger:
        return self._logger

    def _get_credentials(self):
        return delta_storage_options()

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

    async def _capture_unless_transient(self, e: Exception) -> None:
        """capture_exception unless `e` is a known-transient object-store blip (see
        is_transient_object_store_error) — those recover on retry and aren't a defect, so reporting
        them to error tracking is just noise. Never suppresses the re-raise itself, so Temporal's
        activity retry policy is unaffected either way.
        """
        if is_transient_object_store_error(e):
            await self._logger.awarning(f"get_delta_table: transient object-store error, not reporting: {e}")
        else:
            capture_exception(e)

    @conditional_lru_cache_async(maxsize=1, condition=lambda result: result is not None)
    async def get_delta_table(self) -> deltalake.DeltaTable | None:
        delta_uri = await self._get_delta_table_uri()
        storage_options = self._get_credentials()

        try:
            is_delta = await asyncio.to_thread(
                deltalake.DeltaTable.is_deltatable, table_uri=delta_uri, storage_options=storage_options
            )
        except Exception as e:
            # Mirrors the DeltaTable() open below: capture before propagating. Callers range from
            # best-effort maintenance to the main write path, so this can't safely swallow the
            # error and report "no table" here — that would trip should_overwrite_table for a
            # table that actually exists, risking data loss.
            await self._capture_unless_transient(e)
            raise

        if is_delta:
            try:
                return await asyncio.to_thread(
                    deltalake.DeltaTable, table_uri=delta_uri, storage_options=storage_options
                )
            except Exception as e:
                await self._capture_unless_transient(e)
                error_text = "".join(str(arg) for arg in e.args)
                # Unrecoverable tables (bugged decimals, or an orphaned _delta_log missing its
                # metadata action — impossible on a healthy table): wipe so the sync starts fresh.
                if "parse decimal overflow" in error_text or "No table metadata or protocol found" in error_text:
                    await self._logger.aerror(
                        f"get_delta_table: deleting unrecoverable delta table for a fresh sync: {error_text}"
                    )
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
        not corrupt; an unknown open error is not classified as corrupt, so a transient failure never
        triggers a destructive revive.
        """
        delta_uri = await self._get_delta_table_uri()
        storage_options = self._get_credentials()

        is_delta = await asyncio.to_thread(
            deltalake.DeltaTable.is_deltatable, table_uri=delta_uri, storage_options=storage_options
        )
        if not is_delta:
            return False

        try:
            await asyncio.to_thread(deltalake.DeltaTable, table_uri=delta_uri, storage_options=storage_options)
            return False
        except (deltalake.exceptions.DeltaError, FileNotFoundError):
            return True
        except Exception:
            return False

    async def reset_table(self):
        delta_uri = await self._get_delta_table_uri()

        # Explicit purge on a fresh client: a stale dircache or an incomplete recursive delete can
        # leave `_delta_log` strays behind, and the rebuild then commits version 0 into a log that
        # still holds old commits — recreating exactly the corruption a reset is meant to clear.
        async with aget_s3_client(fresh_instance=True) as s3:
            try:
                await _purge_s3_prefix(s3, delta_uri)
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

        deduped = first_per_pk_table(data, dedupe_keys, keep="last")
        dropped = data.num_rows - deduped.num_rows
        if dropped > 0:
            await self._logger.awarning(
                f"write_to_deltalake: dropped {dropped} duplicate primary-key rows "
                f"(keys={dedupe_keys}) from a batch of {data.num_rows} before writing"
            )
        return deduped

    async def _write_via_deltalite(
        self,
        *,
        existing_delta_table: deltalake.DeltaTable,
        data: pa.Table,
        normalized_primary_keys: list[str],
        use_partitioning: bool,
        commit_metadata: dict[str, str] | None,
    ) -> bool:
        """Phase 2: perform the incremental merge via deltalite instead of the delta-rs MERGE.

        Returns True if deltalite committed the write (caller then skips the delta-rs MERGE), or False
        to fall back to the MERGE. Falls back on *anything* — flag off, import failure, deltalite error /
        commit conflict / refusal — so switching a schema to deltalite can only change which engine
        writes, never whether the sync succeeds; the worst case is today's behaviour. Controlled solely
        by the per-schema ``data-warehouse-deltalite-write`` feature flag (no env switch), so it can be
        ramped / killed entirely from the flag UI without a deploy.
        """
        if not normalized_primary_keys:
            return False

        # The flag check is a rollout gate, not part of the write: a flag miss (off) or any error here
        # (including the import) must fall back to the delta-rs MERGE *silently*.
        try:
            from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.deltalite_write import (
                is_deltalite_write_enabled,
            )

            enabled = await database_sync_to_async_pool(is_deltalite_write_enabled)(
                self._job.team_id, str(self._job.schema_id), None
            )
        except Exception:  # noqa: BLE001 - a flag-eval / import error just means "don't use deltalite"
            return False
        if not enabled:
            return False

        # deltalite is enabled. Only the upsert *commit* gates the fallback: a pre-commit failure means
        # nothing was written, so we re-run the delta-rs MERGE. Anything AFTER the commit is best-effort
        # bookkeeping and must NOT return False — otherwise the MERGE would re-run on top of deltalite's
        # already-committed write. (Lazy metrics import keeps the heavy pipeline_v3 chain off the module
        # import path — circular.)
        try:
            import deltalite

            from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.metrics import (
                DELTALITE_WRITE_DURATION_SECONDS,
                DELTALITE_WRITE_TOTAL,
            )

            uri = await self._get_delta_table_uri()
            storage_options = self._get_credentials()
            partition_key = PARTITION_KEY if use_partitioning else None

            def _upsert() -> Any:
                table = deltalite.DeltaLiteTable.open(uri, storage_options)
                return table.upsert(
                    data,
                    list(normalized_primary_keys),
                    partition_key,
                    commit_metadata=commit_metadata,
                )

            started = time.perf_counter()
            stats = await asyncio.to_thread(_upsert)
            duration_s = time.perf_counter() - started
        except Exception as e:  # noqa: BLE001 - pre-commit failure: nothing committed, fall back to MERGE
            await self._logger.awarning(
                f"deltalite write failed; falling back to delta-rs MERGE (sync unaffected): {e}"
            )
            try:
                DELTALITE_WRITE_TOTAL.labels(outcome="fallback").inc()
            except Exception:  # noqa: BLE001 - the metrics import itself failed; the warning is enough
                pass
            return False

        # Committed — the real table is now deltalite's output. NOTHING past this point may raise into
        # the caller: an exception here would leave `deltalite_wrote` unset and either fail/retry the
        # sync or re-run the delta-rs MERGE on top of deltalite's already-committed write. So every
        # post-commit step (handle refresh, log, metric) is wrapped best-effort and we always return True.
        try:
            # Refresh the in-memory delta-rs handle to deltalite's new version so the table returned by
            # write_to_deltalake (and any subsequent reads) reflects the real state.
            await asyncio.to_thread(existing_delta_table.update_incremental)
            # Structured, parseable stats (parity with the old `Delta Merge Stats: {json}` line): every
            # UpsertStats field becomes its own log key, plus the wall-clock duration. `_deltalite_write_stats`
            # enumerates the pyo3 getters, so fields added crate-side later (e.g. per-phase timings) flow
            # through here without a code change.
            await self._logger.ainfo(
                "deltalite write: committed",
                duration_ms=round(duration_s * 1000),
                **_deltalite_write_stats(stats),
            )
            DELTALITE_WRITE_TOTAL.labels(outcome="written").inc()
            DELTALITE_WRITE_DURATION_SECONDS.observe(duration_s)
        except Exception as e:  # noqa: BLE001 - the write is committed; bookkeeping must never raise
            with contextlib.suppress(Exception):
                await self._logger.awarning(f"deltalite write committed but post-commit bookkeeping failed: {e}")
        return True

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
        # realign_decimal_buffers). Sub-tables derived below via filter()/take() are
        # freshly allocated by pyarrow and so inherit safe alignment.
        data = realign_decimal_buffers(data)

        delta_table = await self.get_delta_table()

        if delta_table:
            delta_table = await evolve_delta_schema(delta_table, data.schema)

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

            # The merge casts every source column to its stored column type; a scale-heavy decimal
            # column (e.g. decimal128(38, 32)) overflows that cast on larger values. Align to the
            # stored types up front so the merge cast is a no-op, or raise a clean reset signal.
            data = align_incoming_decimals_to_delta(data, delta_table.schema())

            existing_delta_table = delta_table

            await self._logger.adebug(f"write_to_deltalake: merging...")

            # Normalize keys and check the keys actually exist in the dataset
            py_table_column_names = data.column_names
            normalized_primary_keys: list[str] = []
            for x in primary_keys:
                n = normalize_column_name(x)
                if n in py_table_column_names:
                    normalized_primary_keys.append(n)

            predicate_ops = _merge_predicate_ops(normalized_primary_keys)

            # Phase 2 canary: try deltalite for the real merge. On success the delta-rs MERGE (and the
            # now-redundant forward shadow) below are skipped; on any failure this returns False and we
            # fall through to the MERGE, so a deltalite issue can never fail the sync.
            deltalite_wrote = await self._write_via_deltalite(
                existing_delta_table=existing_delta_table,
                data=data,
                normalized_primary_keys=normalized_primary_keys,
                use_partitioning=use_partitioning,
                commit_metadata=commit_metadata,
            )

            if not deltalite_wrote and use_partitioning:
                predicate_ops.append(f"source.{PARTITION_KEY} = target.{PARTITION_KEY}")

                # Group the table by the partition key and merge multiple times with streamed_exec=True for optimised merging
                unique_partitions = list(pc.unique(data[PARTITION_KEY]))

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

                    # Bind the current loop values as defaults so a conflict retry (which re-calls
                    # this closure) can't accidentally pick up a later iteration's values.
                    def _do_merge(
                        filtered_table: pa.Table = filtered_table,
                        predicate: str = predicate,
                        merge_commit_properties: deltalake.CommitProperties | None = merge_commit_properties,
                    ) -> dict:
                        return (
                            existing_delta_table.merge(
                                source=filtered_table,
                                source_alias="source",
                                target_alias="target",
                                predicate=predicate,
                                streamed_exec=True,
                                commit_properties=merge_commit_properties,
                                **delta_merge_spill_kwargs(),
                            )
                            .when_matched_update_all()
                            .when_not_matched_insert_all()
                            .execute()
                        )

                    merge_stats = await execute_with_conflict_retry(
                        existing_delta_table, _do_merge, "write_to_deltalake: merge", self._logger
                    )

                    await self._logger.adebug(f"Delta Merge Stats: {json.dumps(merge_stats)}")

                    if progress_callback:
                        progress_callback()
            elif not deltalite_wrote:
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
                            **delta_merge_spill_kwargs(),
                        )
                        .when_matched_update_all()
                        .when_not_matched_insert_all()
                        .execute()
                    )

                merge_stats = await execute_with_conflict_retry(
                    existing_delta_table,
                    lambda: _do_merge_unpartitioned(data, predicate_ops),
                    "write_to_deltalake: merge",
                    self._logger,
                )
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
            else:
                # An append re-casts each source column to its stored type, same as a merge. A decimal
                # column that outgrew decimal128 arrives here as text (decimal256 renders to string),
                # and delta-rs can't parse the scientific notation arrow emits for scale-heavy zeros
                # (e.g. '0E-18') back into the stored decimal — an opaque DeltaError that retries
                # forever. Align to the stored decimal types up front, exactly as the merge path does.
                data = align_incoming_decimals_to_delta(data, delta_table.schema())

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
