"""Delivering a run's batches to Redshift.

Redshift speaks the Postgres wire protocol, so this builds on the Postgres writer and on batch
exports' `RedshiftClient`, which is itself a `PostgreSQLClient`. A Redshift destination is
backed by an `aws-redshift` integration, which is a `PostgreSQLServerIntegration` and so
carries the cluster's host, user and password.

Three things genuinely differ and are overridden here:

- No `COPY ... FROM STDIN`. Rows are inserted through a client cursor instead.
- No unbounded `TEXT`. Columns are `VARCHAR(MAX)`, and nested values go in `SUPER`.
- No unique indexes. Upserts are a delete followed by an insert inside one transaction, which
  is the portable form and works on clusters predating Redshift's `MERGE`.

`RedshiftClient.acopy_from_s3_bucket` would be the fast path, since a run's batches are
already parquet in S3. It is not usable as-is: it needs a MANIFEST file and an IAM role or AWS
credentials that let the customer's cluster read the bucket the parquet sits in, which is a
PostHog bucket. Batch exports solve that by staging into a customer-owned bucket first.
Wiring that up here is follow-up work.
"""

from __future__ import annotations

import json
from typing import ClassVar

import pyarrow as pa
from psycopg import sql

from posthog.models.integration.postgres import RedshiftIntegration

from products.batch_exports.backend.temporal.destinations.postgres_batch_export import PostgreSQLClient
from products.batch_exports.backend.temporal.destinations.redshift_batch_export import RedshiftClient
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.postgres import (
    PostgresDestinationWriter,
)

# Redshift's widest string type. Anything longer than this is truncated by the cluster, which
# is preferable to failing the sync outright.
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
    if (
        pa.types.is_list(arrow_type)
        or pa.types.is_large_list(arrow_type)
        or pa.types.is_struct(arrow_type)
        or pa.types.is_map(arrow_type)
    ):
        # SUPER holds semi-structured values without flattening them, so a struct that grows a
        # field keeps loading instead of needing a schema change.
        return "SUPER"
    return VARCHAR_MAX


class RedshiftDestinationWriter(PostgresDestinationWriter):
    holds_sync_lock: ClassVar[bool] = False
    runs_post_load: ClassVar[bool] = False

    def _client_from_integration(self, integration) -> PostgreSQLClient:
        return RedshiftClient.from_inputs(RedshiftIntegration(integration), database=self._database)

    def _column_type(self, arrow_type: pa.DataType) -> str:
        return redshift_type_for(arrow_type)

    async def _ensure_unique_index(self, client: PostgreSQLClient, target: str, primary_keys: list[str]) -> None:
        # Redshift has no unique indexes; uniqueness comes from the delete-then-insert below.
        return None

    async def _write_record_batch(
        self,
        client: PostgreSQLClient,
        target: str,
        batch: pa.RecordBatch,
        ctx,
        *,
        full_refresh: bool,
    ) -> int:
        """Insert rather than COPY FROM STDIN, which Redshift does not support."""
        run = ctx.run
        if batch.num_rows == 0:
            return 0

        column_names = list(batch.schema.names)
        rows = batch.to_pylist()

        if run.is_incremental and run.primary_keys and not full_refresh:
            await self._delete_then_insert(client, target, column_names, rows, list(run.primary_keys))
            return len(rows)

        await self._insert(
            client,
            target,
            column_names,
            rows,
            batch_index=ctx.batch_index if full_refresh else None,
        )
        return len(rows)

    async def _insert(
        self,
        client: PostgreSQLClient,
        target: str,
        column_names: list[str],
        rows: list[dict],
        *,
        batch_index: int | None,
    ) -> None:
        columns = [*column_names] + ([self._batch_index_column] if batch_index is not None else [])
        statement = sql.SQL("INSERT INTO {}.{} ({}) VALUES ({})").format(
            sql.Identifier(self._schema),
            sql.Identifier(target),
            sql.SQL(", ").join(sql.Identifier(c) for c in columns),
            sql.SQL(", ").join(sql.Placeholder() for _ in columns),
        )
        payload = []
        for row in rows:
            values = [_encode(row.get(name)) for name in column_names]
            if batch_index is not None:
                values.append(batch_index)
            payload.append(values)

        async with client.connection.cursor() as cursor:
            await cursor.executemany(statement, payload)

    async def _delete_then_insert(
        self,
        client: PostgreSQLClient,
        target: str,
        column_names: list[str],
        rows: list[dict],
        primary_keys: list[str],
    ) -> None:
        """Upsert by deleting the incoming keys and inserting the batch, in one transaction.

        Both halves run together so a reader never sees the deleted rows missing, and so a
        re-applied batch converges on the same result.
        """
        key_tuples = [tuple(row.get(key) for key in primary_keys) for row in rows]

        async with client.connection.transaction():
            delete = sql.SQL("DELETE FROM {}.{} WHERE ({}) IN ({})").format(
                sql.Identifier(self._schema),
                sql.Identifier(target),
                sql.SQL(", ").join(sql.Identifier(key) for key in primary_keys),
                sql.SQL(", ").join(
                    sql.SQL("({})").format(sql.SQL(", ").join(sql.Placeholder() for _ in primary_keys))
                    for _ in key_tuples
                ),
            )
            async with client.connection.cursor() as cursor:
                await cursor.execute(delete, [value for key_tuple in key_tuples for value in key_tuple])

            await self._insert(client, target, column_names, rows, batch_index=None)


def _encode(value):
    """Send nested values as JSON text, which Redshift parses into SUPER."""
    if isinstance(value, dict | list):
        return json.dumps(value)
    return value
