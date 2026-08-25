import json
import time
import asyncio
import contextlib
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Literal

import pyarrow as pa
import deltalake
import pyarrow.compute as pc
import deltalake.exceptions

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    MISSING_PRIMARY_KEYS_ERROR,
    MissingPrimaryKeysException,
    align_incoming_decimals_to_delta,
    first_per_pk_table,
    normalize_column_name,
    raise_on_nullability_drift,
    realign_decimal_buffers,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.consts import PARTITION_KEY
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.evolution import evolve_delta_schema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.ops import (
    delta_merge_spill_kwargs,
    execute_with_conflict_retry,
)
from products.warehouse_sources.backend.temporal.data_imports.workload_report import report_buffer_bytes, report_phase

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef


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


def commit_matches(commit: dict[str, Any], match: dict[str, str]) -> bool:
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


class DeltaWriter:
    """The core write/merge path for one schema's Delta table, plus commit-metadata idempotency.

    Stateless over a `DeltaTableRef`, which holds the cached table handle and the first-sync
    flag — construct one at the call site. Tagging commits with `commit_metadata` and reading the
    tags back (`has_batch_been_committed`) live together because they are two halves of one
    contract: only the terminal commit of a multi-commit write may carry the tag, or a redelivery
    after a mid-write crash would treat the batch as done and lose data.
    """

    def __init__(self, table: "DeltaTableRef") -> None:
        self._table = table
        self._logger = table.logger

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
                f"write: dropped {dropped} duplicate primary-key rows "
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
                self._table.job.team_id, str(self._table.job.schema_id), None
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

            from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.memory_governor import (
                get_governor,
            )
            from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.metrics import (
                DELTALITE_WRITE_DURATION_SECONDS,
                DELTALITE_WRITE_TOTAL,
            )

            uri = await self._table.get_table_uri()
            storage_options = self._table.get_storage_options()
            partition_key = PARTITION_KEY if use_partitioning else None
            n_partitions = (
                pc.count_distinct(data[PARTITION_KEY]).as_py()
                if use_partitioning and PARTITION_KEY in data.column_names
                else None
            )

            # Capacity planning: size this upsert's knobs to a fixed per-upsert slice of pod memory,
            # so all MAX_CONCURRENT_ACTIVITIES upserts on this process are guaranteed to fit. deltalite
            # always writes — the governor never falls back to the delta-rs MERGE for capacity, because
            # the MERGE is the *more* memory-hungry path. A source too big for its slice just runs at
            # mpp=1 (governor logs a capacity_exceeded ops signal).
            async with get_governor().admit(source_bytes=data.nbytes, n_partitions=n_partitions) as adm:

                def _upsert(upsert_kwargs: dict[str, int] = adm.upsert_kwargs) -> Any:
                    table = deltalite.DeltaLiteTable.open(uri, storage_options)
                    return table.upsert(
                        data,
                        list(normalized_primary_keys),
                        partition_key,
                        commit_metadata=commit_metadata,
                        **upsert_kwargs,
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
            # write (and any subsequent reads) reflects the real state.
            await asyncio.to_thread(existing_delta_table.update_incremental)
            # Structured, parseable stats (parity with the old `Delta Merge Stats: {json}` line): every
            # UpsertStats field becomes its own log key, plus the wall-clock duration. `_deltalite_write_stats`
            # enumerates the pyo3 getters, so fields added crate-side later (e.g. per-phase timings) flow
            # through here without a code change.
            await self._logger.ainfo(
                "deltalite write: committed",
                duration_ms=round(duration_s * 1000),
                governor_mode=adm.mode,
                governor_predicted_peak_mb=adm.predicted_peak_mb,
                governor_observed_delta_mb=adm.observed_delta_mb,
                governor_budget_mb=adm.budget_mb,
                governor_capacity_exceeded=adm.capacity_exceeded,
                governor_mpp=adm.planned_mpp,
                **_deltalite_write_stats(stats),
            )
            DELTALITE_WRITE_TOTAL.labels(outcome="written").inc()
            DELTALITE_WRITE_DURATION_SECONDS.observe(duration_s)
        except Exception as e:  # noqa: BLE001 - the write is committed; bookkeeping must never raise
            with contextlib.suppress(Exception):
                await self._logger.awarning(f"deltalite write committed but post-commit bookkeeping failed: {e}")
        return True

    async def write(
        self,
        data: pa.Table,
        write_type: Literal["incremental", "full_refresh", "append"],
        should_overwrite_table: bool,
        primary_keys: Sequence[Any] | None,
        progress_callback: Callable[[], None] | None = None,
        commit_metadata: dict[str, str] | None = None,
    ) -> deltalake.DeltaTable:
        # `.nbytes` rather than the slice-accurate accounting: tables reaching the writer are
        # materialised chunks, not zero-copy slices, and the merge working set scales with the full
        # buffers delta-rs will read anyway. This reports the merge *input* only — the decompressed
        # target-partition working set lives inside delta-rs/DataFusion where we can't observe it,
        # and under deltalite the memory governor bounds it; the input batch is the per-activity
        # share we can actually attribute.
        report_phase("merge")
        report_buffer_bytes(data.nbytes)

        # Guard against delta-rs aborting the worker on misaligned decimal buffers (see
        # realign_decimal_buffers). Sub-tables derived below via filter()/take() are
        # freshly allocated by pyarrow and so inherit safe alignment.
        data = realign_decimal_buffers(data)

        delta_table = await self._table.get_delta_table()

        if delta_table:
            delta_table = await evolve_delta_schema(delta_table, data.schema)

        is_first_sync = self._table.is_first_sync
        await self._logger.adebug(
            f"write: is_first_sync = {is_first_sync}. should_overwrite_table = {should_overwrite_table}"
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

        if write_type == "incremental" and delta_table is not None and not is_first_sync:
            if not primary_keys or len(primary_keys) == 0:
                raise MissingPrimaryKeysException()

            # The merge casts every source column to its stored column type; a scale-heavy decimal
            # column (e.g. decimal128(38, 32)) overflows that cast on larger values. Align to the
            # stored types up front so the merge cast is a no-op, or raise a clean reset signal.
            data = align_incoming_decimals_to_delta(data, delta_table.schema())

            existing_delta_table = delta_table

            await self._logger.adebug(f"write: merging...")

            # Normalize keys and check the keys actually exist in the dataset
            py_table_column_names = data.column_names
            normalized_primary_keys: list[str] = []
            for x in primary_keys:
                n = normalize_column_name(x)
                if n in py_table_column_names:
                    normalized_primary_keys.append(n)

            if not normalized_primary_keys:
                # None of the configured primary key columns survived into this batch (e.g. a stale
                # persisted key name that no longer matches the source's columns). Left unguarded, the
                # unpartitioned path below joins an empty predicate_ops into "" and hands delta-rs an
                # empty predicate, which its SQL parser rejects with an opaque "Expected: an expression,
                # found: EOF" — and the partitioned path would merge on partition alone, matching rows
                # that were never actually the same record. Fail clearly instead of either.
                raise MissingPrimaryKeysException(
                    f"{MISSING_PRIMARY_KEYS_ERROR}: none of {list(primary_keys)!r} were found in the "
                    f"synced data (columns: {py_table_column_names!r})"
                )

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

            if not deltalite_wrote:
                # A batch with nulls in a column the table declares non-nullable: deltalite relaxes
                # the column to nullable in the table metadata and writes, but the delta-rs MERGE
                # cannot relax in place and would silently write the nulls under a schema that
                # denies them. Guard only the fallback path with the reset signal.
                raise_on_nullability_drift(data, delta_table.schema())

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
                        existing_delta_table, _do_merge, "write: merge", self._logger
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
                    "write: merge",
                    self._logger,
                )
                await self._logger.adebug(f"Delta Merge Stats: {json.dumps(merge_stats)}")
        elif (
            write_type == "full_refresh"
            or (write_type == "incremental" and delta_table is None)
            or (write_type == "incremental" and is_first_sync)
        ):
            mode: Literal["error", "append", "overwrite", "ignore"] = "append"
            schema_mode: Literal["merge", "overwrite"] | None = "merge"
            if should_overwrite_table or delta_table is None:
                mode = "overwrite"
                schema_mode = "overwrite"

            await self._logger.adebug(f"write: mode = {mode}")

            if delta_table is None:
                storage_options = self._table.get_storage_options()
                delta_uri = await self._table.get_table_uri()
                # mode="ignore": a zombie Temporal attempt (heartbeat-timed-out but still running
                # while its retry starts — see this package's README) or a stale get_delta_table()
                # check can race another writer that already created this table. "ignore" opens
                # the winner's table instead of erroring; the write below then applies our data on
                # top of it, so the race can only change who created the table, never the outcome.
                delta_table = await asyncio.to_thread(
                    deltalake.DeltaTable.create,
                    table_uri=delta_uri,
                    schema=data.schema,
                    storage_options=storage_options,
                    partition_by=PARTITION_KEY if use_partitioning else None,
                    mode="ignore",
                )

            if mode == "append":
                # Each batch of a full_refresh (or first incremental sync) infers its own decimal
                # types independently, same as the incremental-merge and append-continuation paths
                # above. Without reconciling to the table's already-established type here, a later
                # batch whose inferred scale is wider than an earlier one hits delta-rs's
                # merge-schema SchemaMismatchError, since schema_mode="merge" can't widen a stored
                # column's type in place.
                data = align_incoming_decimals_to_delta(data, delta_table.schema())

            try:
                await execute_with_conflict_retry(
                    delta_table,
                    lambda: _write_deltalake(
                        delta_table,
                        data,
                        partition_by=PARTITION_KEY if use_partitioning else None,
                        mode=mode,
                        schema_mode=schema_mode,
                        commit_properties=commit_properties,
                    ),
                    "write: overwrite",
                    self._logger,
                )
            except deltalake.exceptions.SchemaMismatchError as e:
                await self._logger.adebug("SchemaMismatchError: attempting to overwrite schema instead", exc_info=e)
                capture_exception(e)

                await execute_with_conflict_retry(
                    delta_table,
                    lambda: _write_deltalake(
                        delta_table,
                        data,
                        partition_by=None,
                        mode=mode,
                        schema_mode="overwrite",
                        commit_properties=commit_properties,
                    ),
                    "write: overwrite (schema retry)",
                    self._logger,
                )
        elif write_type == "append":
            if delta_table is None:
                storage_options = self._table.get_storage_options()
                delta_uri = await self._table.get_table_uri()
                # See the full_refresh branch above for why mode="ignore" is required here.
                delta_table = await asyncio.to_thread(
                    deltalake.DeltaTable.create,
                    table_uri=delta_uri,
                    schema=data.schema,
                    storage_options=storage_options,
                    partition_by=PARTITION_KEY if use_partitioning else None,
                    mode="ignore",
                )
            else:
                # An append re-casts each source column to its stored type, same as a merge. A decimal
                # column that outgrew decimal128 arrives here as text (decimal256 renders to string),
                # and delta-rs can't parse the scientific notation arrow emits for scale-heavy zeros
                # (e.g. '0E-18') back into the stored decimal — an opaque DeltaError that retries
                # forever. Align to the stored decimal types up front, exactly as the merge path does.
                data = align_incoming_decimals_to_delta(data, delta_table.schema())

            await self._logger.adebug(f"write: write_type = append")

            await execute_with_conflict_retry(
                delta_table,
                lambda: _write_deltalake(
                    delta_table,
                    data,
                    partition_by=PARTITION_KEY if use_partitioning else None,
                    mode="append",
                    schema_mode="merge",
                    commit_properties=commit_properties,
                ),
                "write: append",
                self._logger,
            )

        delta_table = await self._table.get_delta_table()
        assert delta_table is not None

        return delta_table

    async def has_commit_with_metadata(self, match: dict[str, str], *, scan_limit: int = 50) -> bool:
        """Check whether any recent delta commit has custom metadata matching all entries in `match`.

        Used to detect that a given (run_uuid, batch_index) has already been written
        even when a faster external dedup cache (e.g. Redis) is missing the marker —
        the canonical case is a writer crash between a successful `write`
        and the subsequent cache update.

        delta-rs `history()` returns commits where `CommitProperties.custom_metadata`
        entries are flattened directly into the commit dict alongside `operation`,
        `timestamp`, etc. Older versions nested them under a `userMetadata` key, so
        we accept both layouts for forward compatibility.
        """
        delta_table = await self._table.get_delta_table()
        if delta_table is None:
            return False

        history = await asyncio.to_thread(delta_table.history, limit=scan_limit)

        for commit in history:
            if commit_matches(commit, match):
                return True

        return False

    async def has_batch_been_committed(self, run_uuid: str, batch_index: int) -> bool:
        """Check whether a specific (run_uuid, batch_index) has already been committed to delta.

        Thin wrapper around `has_commit_with_metadata` so callers don't need to know
        the metadata schema used for idempotency tagging.
        """
        return await self.has_commit_with_metadata({"run_uuid": run_uuid, "batch_index": str(batch_index)})
