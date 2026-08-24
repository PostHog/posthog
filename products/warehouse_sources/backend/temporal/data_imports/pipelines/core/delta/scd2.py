import json
import asyncio
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import pyarrow as pa
import deltalake

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    first_per_pk_table,
    normalize_column_name,
    realign_decimal_buffers,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.evolution import evolve_delta_schema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.ops import (
    delta_merge_spill_kwargs,
    execute_with_conflict_retry,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef


class Scd2DeltaWriter:
    """SCD Type 2 writer over one schema's Delta table.

    Stateless over a `DeltaTableRef`, which holds the cached table handle — construct one at
    the call site. The validity-interval column names are injected so the writer stays generic;
    today's only caller is the CDC load path, which passes the columns `cdc/batcher.py` stamps
    via `build_scd2_table`.
    """

    def __init__(self, table: "DeltaTableRef", *, valid_from_column: str, valid_to_column: str) -> None:
        self._table = table
        self._logger = table.logger
        self._valid_from_column = valid_from_column
        self._valid_to_column = valid_to_column

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

        delta_table = await self._table.get_delta_table()

        if delta_table:
            delta_table = await evolve_delta_schema(delta_table, data.schema)

        commit_properties: deltalake.CommitProperties | None = (
            deltalake.CommitProperties(custom_metadata=commit_metadata) if commit_metadata else None
        )

        # Step 1: Close existing current rows for PKs in this batch
        if delta_table is not None and primary_keys and self._valid_from_column in data.column_names:
            existing_delta_table = delta_table
            py_column_names = data.column_names
            normalized_pks: list[str] = []
            for x in primary_keys:
                n = normalize_column_name(x)
                if n in py_column_names:
                    normalized_pks.append(n)

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
            )

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
        return delta_table
