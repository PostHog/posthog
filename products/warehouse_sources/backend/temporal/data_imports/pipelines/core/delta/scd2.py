import json
import asyncio
from collections.abc import Collection, Sequence
from typing import TYPE_CHECKING, Any

import pyarrow as pa
import deltalake
import pyarrow.compute as pc
import pyarrow.dataset as pa_ds

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    first_per_pk_table,
    normalize_column_name,
    realign_decimal_buffers,
    relax_batch_nullability,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.evolution import evolve_delta_schema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.ops import (
    DELTA_TABLE_PROPERTIES,
    delta_merge_spill_kwargs,
    ensure_table_properties,
    execute_with_conflict_retry,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.row_hash import (
    compute_row_hashes,
    is_current_row_hash,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef


def _key_tuples(table: pa.Table, primary_keys: list[str]) -> list[tuple[Any, ...]]:
    return list(zip(*(table.column(name).to_pylist() for name in primary_keys)))


class Scd2DeltaWriter:
    """SCD Type 2 writer over one schema's Delta table.

    Stateless over a `DeltaTableRef`, which holds the cached table handle — construct one at
    the call site. The validity-interval column names are injected so the writer stays generic;
    today's only caller is the CDC load path, which passes the columns `cdc/batcher.py` stamps
    via `build_scd2_table`.

    Passing `row_hash_column` turns on skip-unchanged: the writer stores a content hash of each
    row in that column, and drops an incoming row that equals the current row of its key.
    `row_hash_exclude_columns` names the columns that change on every sync without the row
    changing. Changing that set changes every hash, so every row reads as changed once.
    """

    def __init__(
        self,
        table: "DeltaTableRef",
        *,
        valid_from_column: str,
        valid_to_column: str,
        row_hash_column: str | None = None,
        row_hash_exclude_columns: Collection[str] = (),
    ) -> None:
        self._table = table
        self._logger = table.logger
        self._valid_from_column = valid_from_column
        self._valid_to_column = valid_to_column
        self._row_hash_column = row_hash_column
        # Batch columns arrive normalized, so a raw source name here would never match and every
        # row would read as changed.
        excluded = {normalize_column_name(name) for name in row_hash_exclude_columns}
        self._unhashed_columns = {valid_from_column, valid_to_column, *excluded}
        if row_hash_column is not None:
            self._unhashed_columns.add(row_hash_column)

    def _drop_unchanged_rows(
        self, delta_table: deltalake.DeltaTable, data: pa.Table, primary_keys: list[str]
    ) -> pa.Table:
        """Drop the leading rows of each key whose hash equals the hash of the key's current row.

        Only leading rows go. A later row of the same key keeps the `valid_to` chain the caller
        stamped, and dropping it would leave the row before it closed at the wrong time.
        """
        assert self._row_hash_column is not None
        current_hashes = self._current_row_hashes(delta_table, data, primary_keys)
        if not current_hashes:
            return data

        changed_keys: set[tuple[Any, ...]] = set()
        keep: list[bool] = []
        for key, row_hash in zip(_key_tuples(data, primary_keys), data.column(self._row_hash_column).to_pylist()):
            unchanged = key not in changed_keys and current_hashes.get(key) == row_hash
            if not unchanged:
                changed_keys.add(key)
            keep.append(not unchanged)

        return data if all(keep) else data.filter(pa.array(keep, type=pa.bool_()))

    def _current_row_hashes(
        self, delta_table: deltalake.DeltaTable, data: pa.Table, primary_keys: list[str]
    ) -> dict[tuple[Any, ...], str | None]:
        assert self._row_hash_column is not None
        dataset = delta_table.to_pyarrow_dataset()
        rows = dataset.to_table(
            columns=[*primary_keys, self._row_hash_column],
            filter=self._current_rows_filter(dataset, data, primary_keys),
        )
        hashes = rows.column(self._row_hash_column).to_pylist()
        current_hashes = dict(zip(_key_tuples(rows, primary_keys), hashes))

        is_stale = pa.array([not is_current_row_hash(row_hash) for row_hash in hashes], type=pa.bool_())
        if is_stale.true_count:
            # A row written before skip-unchanged was on, or under another hash version, has no
            # comparable hash. Hash its stored values instead, so that it does not read as changed.
            stale_keys = rows.filter(is_stale).select(primary_keys)
            stale_rows = dataset.to_table(filter=self._current_rows_filter(dataset, stale_keys, primary_keys))
            stale_hashes = compute_row_hashes(stale_rows, self._unhashed_columns).to_pylist()
            for key, row_hash in zip(_key_tuples(stale_rows, primary_keys), stale_hashes):
                if not is_current_row_hash(current_hashes.get(key)):
                    current_hashes[key] = row_hash

        return current_hashes

    def _current_rows_filter(self, dataset: pa_ds.Dataset, keys: pa.Table, primary_keys: list[str]) -> pc.Expression:
        """Match the current rows whose key columns each hold a value from `keys`.

        For a composite key this also matches some keys that are not in `keys`. The caller looks
        rows up by the full key, so those extra rows are never compared.
        """
        expression = pc.field(self._valid_to_column).is_null()
        for name in primary_keys:
            wanted = pc.unique(keys.column(name)).cast(dataset.schema.field(name).type)
            expression = expression & pc.field(name).isin(wanted)
        return expression

    async def write(
        self,
        data: pa.Table,
        primary_keys: Sequence[Any],
        commit_metadata: dict[str, str] | None = None,
    ) -> deltalake.DeltaTable:
        """Write SCD Type 2 data: close existing current rows, then append new rows.

        For each PK that appears in `data`:
        1. Find the existing row in the target with matching PK and valid_to IS NULL
           (the current row) and update its valid_to to the earliest valid_from of the
           new events for that PK.
        2. Append all rows from `data` as new history entries.

        `data` is expected to already carry the valid_from / valid_to columns.
        """
        # See realign_decimal_buffers. The close-existing merge uses first_per_pk_table(data),
        # whose take() output is freshly allocated, so realigning `data` here covers both the
        # close and the append.
        data = realign_decimal_buffers(data)

        # A source can declare a column NOT NULL and still send nulls in it, and both delta calls
        # below refuse such a batch. Correct the claim before either runs (see
        # relax_batch_nullability).
        data = relax_batch_nullability(data)

        if self._row_hash_column is not None:
            if self._row_hash_column in data.column_names:
                raise ValueError(
                    f"Source column {self._row_hash_column!r} collides with the history table's row hash column"
                )
            data = data.append_column(self._row_hash_column, compute_row_hashes(data, self._unhashed_columns))

        delta_table = await self._table.get_delta_table()

        if delta_table:
            delta_table = await evolve_delta_schema(delta_table, data.schema)

        normalized_pks = [n for n in (normalize_column_name(x) for x in primary_keys) if n in data.column_names]

        if self._row_hash_column is not None and delta_table is not None and normalized_pks:
            incoming_rows = data.num_rows
            data = await asyncio.to_thread(self._drop_unchanged_rows, delta_table, data, normalized_pks)
            await self._logger.adebug(f"SCD2 skipped {incoming_rows - data.num_rows} unchanged rows of {incoming_rows}")
            if data.num_rows == 0:
                return delta_table

        commit_properties: deltalake.CommitProperties | None = (
            deltalake.CommitProperties(custom_metadata=commit_metadata) if commit_metadata else None
        )

        # Step 1: Close existing current rows for PKs in this batch
        if delta_table is not None and primary_keys and self._valid_from_column in data.column_names:
            existing_delta_table = delta_table

            if normalized_pks:
                # Use only the first row per PK to avoid ambiguous multi-match merge
                first_per_pk = first_per_pk_table(data, normalized_pks)

                predicate_parts = [f"source.{col} = target.{col}" for col in normalized_pks]
                predicate_parts.append(f"target.{self._valid_to_column} IS NULL")
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
                            **delta_merge_spill_kwargs(),
                        )
                        .when_matched_update(updates={self._valid_to_column: f"source.{self._valid_from_column}"})
                        .execute()
                    )

                close_stats = await execute_with_conflict_retry(
                    existing_delta_table,
                    lambda: _do_scd2_close(first_per_pk, predicate),
                    "Scd2DeltaWriter.write: close merge",
                    self._logger,
                )
                await self._logger.adebug(f"SCD2 close stats: {json.dumps(close_stats)}")

        # Step 2: Append all new rows
        if delta_table is None:
            storage_options = self._table.get_storage_options()
            delta_uri = await self._table.get_table_uri()
            delta_table = await asyncio.to_thread(
                deltalake.DeltaTable.create,
                table_uri=delta_uri,
                schema=data.schema,
                storage_options=storage_options,
                configuration=DELTA_TABLE_PROPERTIES,
            )
            self._table.adopt_created_table(delta_table)

        await asyncio.to_thread(
            deltalake.write_deltalake,
            table_or_uri=delta_table,
            data=data,
            mode="append",
            schema_mode="merge",
            commit_properties=commit_properties,
        )

        delta_table = await self._table.get_delta_table()
        assert delta_table is not None

        await ensure_table_properties(delta_table, self._logger)
        return delta_table
