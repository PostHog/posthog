"""Delivering a run's batches to Redshift.

Redshift speaks the Postgres wire protocol, so this builds on the Postgres writer and on batch
exports' `RedshiftClient`, which is itself a `PostgreSQLClient`. A Redshift destination is
backed by an `aws-redshift` integration, which is a `PostgreSQLServerIntegration` and so
carries the cluster's host, user and password.

Three things genuinely differ and are overridden here:

- No `COPY ... FROM STDIN`. Rows are inserted through a client cursor instead.
- No unbounded `TEXT`. Columns are `VARCHAR(MAX)`, and nested values go in `SUPER`.
- No unique indexes, so no `ON CONFLICT`. Upserts go through `RedshiftClient.amerge_tables`,
  which merges on the key alone once its version-aware delete is turned off.

`RedshiftClient.acopy_from_s3_bucket` would be the fast path, since a run's batches are
already parquet in S3. It is not usable as-is: it needs a MANIFEST file and an IAM role or AWS
credentials that let the customer's cluster read the bucket the parquet sits in, which is a
PostHog bucket. Batch exports solve that by staging into a customer-owned bucket first.
Wiring that up here is follow-up work.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar, cast

import pyarrow as pa
from psycopg import sql

from posthog.models.integration import Integration, RedshiftIntegration

from products.batch_exports.backend.temporal.destinations.postgres_batch_export import Fields, PostgreSQLClient
from products.batch_exports.backend.temporal.destinations.redshift_batch_export import RedshiftClient
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.postgres import (
    PostgresDestinationWriter,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.sql_types import (
    is_nested_type,
)

# Redshift's widest string type, which holds 65535 bytes. Nothing here asks the cluster to
# truncate, so a longer value fails the statement instead of being cut short: batch exports
# reports the same overflow as `StringLimitExceededError` and never retries it.
VARCHAR_MAX = "VARCHAR(MAX)"

_REDSHIFT_BY_ARROW = {
    pa.bool_(): "BOOLEAN",
    pa.int8(): "SMALLINT",
    pa.int16(): "SMALLINT",
    pa.int32(): "INTEGER",
    pa.int64(): "BIGINT",
    pa.uint8(): "SMALLINT",
    pa.uint16(): "INTEGER",
    pa.uint32(): "BIGINT",
    pa.uint64(): "NUMERIC(20, 0)",
    pa.float16(): "REAL",
    pa.float32(): "REAL",
    pa.float64(): "DOUBLE PRECISION",
    pa.string(): VARCHAR_MAX,
    pa.large_string(): VARCHAR_MAX,
    pa.binary(): VARCHAR_MAX,
    pa.large_binary(): VARCHAR_MAX,
    pa.date32(): "DATE",
    pa.date64(): "DATE",
}


def redshift_type_for(arrow_type: pa.DataType) -> str:
    mapped = _REDSHIFT_BY_ARROW.get(arrow_type)
    if mapped is not None:
        return mapped
    if pa.types.is_timestamp(arrow_type):
        return "TIMESTAMPTZ" if arrow_type.tz else "TIMESTAMP"
    if pa.types.is_time(arrow_type):
        return "TIME"
    if pa.types.is_decimal(arrow_type):
        return f"NUMERIC({arrow_type.precision}, {arrow_type.scale})"
    if is_nested_type(arrow_type):
        # SUPER holds semi-structured values without flattening them, so a struct that grows a
        # field keeps loading instead of needing a schema change.
        return "SUPER"
    return VARCHAR_MAX


class RedshiftDestinationWriter(PostgresDestinationWriter):
    holds_sync_lock: ClassVar[bool] = False
    runs_post_load: ClassVar[bool] = False

    integration_kind: ClassVar[str] = RedshiftIntegration.integration_kind

    def _client_from_integration(self, integration: Integration) -> PostgreSQLClient:
        return RedshiftClient.from_inputs(RedshiftIntegration(integration), database=self._database)

    def _column_type(self, arrow_type: pa.DataType) -> str:
        return redshift_type_for(arrow_type)

    async def _load_batch(
        self, client: PostgreSQLClient, table: str, batch: pa.RecordBatch, column_names: list[str]
    ) -> None:
        """Insert rather than COPY FROM STDIN, which Redshift does not support."""
        nested = {field.name for field in batch.schema if is_nested_type(field.type)}
        statement = sql.SQL("INSERT INTO {}.{} ({}) VALUES ({})").format(
            sql.Identifier(self._schema),
            sql.Identifier(table),
            sql.SQL(", ").join(sql.Identifier(c) for c in column_names),
            # A JSON string bound straight into a SUPER column is stored as a string scalar,
            # so `col.key` navigation over it returns NULL. `JSON_PARSE` is what turns the text
            # into the SUPER structure the column was created to hold.
            sql.SQL(", ").join(
                sql.SQL("JSON_PARSE({})").format(sql.Placeholder()) if c in nested else sql.Placeholder()
                for c in column_names
            ),
        )
        payload = [[_encode(record.get(name)) for name in column_names] for record in batch.to_pylist()]

        async with self._write_cursor(client) as cursor:
            await cursor.executemany(statement, payload)

    async def _ensure_merge_stage(self, client: PostgreSQLClient, target: str, stage: str, schema: pa.Schema) -> None:
        """Ready the run's stage table as a copy of the destination table.

        `amerge_tables` selects the destination's full column list out of the stage and inserts
        an unmatched row positionally, so the stage has to carry the destination's own columns
        in the destination's own order. A stage built from the batch alone is short of any
        column the destination grew on an earlier run, and the merge's `SELECT` then names a
        column the stage does not have. Copying the destination's definition is the only way to
        hold that for a table this writer grows column by column. Columns the batch does not
        carry stay NULL, which is what the row would have held anyway.

        Created once per run and emptied between batches, same as the base writer's stage, and
        dropped by `abort_run` and `finalize_run`.
        """
        async with self._write_cursor(client) as cursor:
            await cursor.execute(
                sql.SQL("CREATE TABLE IF NOT EXISTS {}.{} (LIKE {}.{})").format(
                    sql.Identifier(self._schema),
                    sql.Identifier(stage),
                    sql.Identifier(self._schema),
                    sql.Identifier(target),
                )
            )

        # The stage outlives the batch that created it, so a column the source grew mid-run has
        # to reach it too, or the insert names a column the stage does not have.
        await self._evolve_table(client, stage, schema)
        async with self._write_cursor(client) as cursor:
            await cursor.execute(
                sql.SQL("TRUNCATE TABLE {}.{}").format(sql.Identifier(self._schema), sql.Identifier(stage))
            )

    async def _upsert_from_stage(
        self,
        client: PostgreSQLClient,
        target: str,
        stage: str,
        column_names: list[str],
        primary_keys: list[str],
    ) -> None:
        """Merge the stage into the destination on the primary keys.

        `skip_delete` turns off the pass `amerge_tables` runs for the person model, which
        drops stage rows older than the row they would replace and so needs a column that only
        ever increases. A synced source table has none, and without that pass what is left is
        a plain upsert on the merge key. Going through `amerge_tables` still brings the
        `SERIALIZABLE` lock, the schema-mismatch diagnostic and the string-limit mapping.
        """
        # The stage was created from the destination, so both share this order. Only the name
        # in each field is read, which is why the types are left empty.
        final_table_fields: Fields = [(name, "") for name in await client.aget_table_columns(self._schema, target)]
        merge_key: Fields = [(key, "") for key in primary_keys]

        await cast(RedshiftClient, client).amerge_tables(
            final_table_name=target,
            stage_table_name=stage,
            schema=self._schema,
            merge_key=merge_key,
            # Only read to build the delete that `skip_delete` suppresses.
            update_key=[],
            final_table_fields=final_table_fields,
            remove_duplicates=False,
            skip_delete=True,
        )


def _encode(value: Any) -> Any:
    """Send nested values as JSON text, which Redshift parses into SUPER."""
    if isinstance(value, dict | list):
        return json.dumps(value)
    return value
