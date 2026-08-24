import uuid
from collections.abc import AsyncIterator

import pytest

from django.conf import settings

import psycopg
import pyarrow as pa
import psycopg.conninfo

from products.batch_exports.backend.temporal.destinations.postgres_batch_export import PostgreSQLClient
from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import (
    DestinationBatchContext,
    DestinationRunContext,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.postgres import (
    PostgresDestinationWriter,
    staging_table_name,
)

pytestmark = pytest.mark.asyncio


async def _batches(*record_batches: pa.RecordBatch) -> AsyncIterator[pa.RecordBatch]:
    for batch in record_batches:
        yield batch


def _rows(name: list[str], ids: list[int]) -> pa.RecordBatch:
    return pa.RecordBatch.from_pydict({"id": ids, "name": name})


class LocalPostgresWriter(PostgresDestinationWriter):
    """Points the writer at the local test database instead of a customer's integration."""

    def __init__(self, ctx: DestinationRunContext, dsn: str) -> None:
        super().__init__(ctx)
        self._dsn = dsn

    async def _make_client(self) -> PostgreSQLClient:
        parsed = psycopg.conninfo.conninfo_to_dict(self._dsn)
        return PostgreSQLClient(
            user=str(parsed.get("user", "posthog")),
            password=str(parsed.get("password", "posthog")),
            host=str(parsed.get("host", "localhost")),
            port=int(parsed.get("port") or 5432),
            database=str(parsed.get("dbname", "posthog")),
            ssl_mode="prefer",
        )


@pytest.fixture
def dsn() -> str:
    return settings.WAREHOUSE_SOURCES_DATABASE_URL


@pytest.fixture
def table_name() -> str:
    return f"dest_test_{uuid.uuid4().hex[:10]}"


def _ctx(table_name: str, sync_type: str, primary_keys: tuple[str, ...] = ()) -> DestinationRunContext:
    return DestinationRunContext(
        team_id=1,
        schema_id="schema",
        source_id="source",
        job_id="job",
        run_uuid=str(uuid.uuid4()),
        destination_id="destination",
        destination_type="Postgres",
        destination_name="test postgres",
        table_name=table_name,
        sync_type=sync_type,
        primary_keys=primary_keys,
        config={"schema": "public"},
    )


def _read(dsn: str, table: str) -> list[tuple]:
    with psycopg.connect(dsn, autocommit=True) as conn:
        return conn.execute(f'SELECT id, name FROM public."{table}" ORDER BY id').fetchall()


def _drop(dsn: str, *tables: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        for table in tables:
            conn.execute(f'DROP TABLE IF EXISTS public."{table}" CASCADE')


class TestFullRefresh:
    async def test_the_live_table_only_changes_once_the_run_completes(self, dsn, table_name) -> None:
        ctx = _ctx(table_name, "full_refresh")
        writer = LocalPostgresWriter(ctx, dsn)
        try:
            await writer.write_batch(
                _batches(_rows(["a"], [1])),
                DestinationBatchContext(run=ctx, batch_index=0, is_final_batch=False),
            )

            # Mid-run the destination table does not exist yet; only the staging table does.
            with psycopg.connect(dsn, autocommit=True) as conn:
                live_exists = conn.execute(
                    "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s",
                    (table_name,),
                ).fetchone()
            assert live_exists is None

            await writer.write_batch(
                _batches(_rows(["b"], [2])),
                DestinationBatchContext(run=ctx, batch_index=1, is_final_batch=True),
            )
            await writer.finalize_run(ctx)

            assert _read(dsn, table_name) == [(1, "a"), (2, "b")]
        finally:
            _drop(dsn, table_name, staging_table_name(ctx))

    async def test_reapplying_a_batch_does_not_duplicate_its_rows(self, dsn, table_name) -> None:
        ctx = _ctx(table_name, "full_refresh")
        writer = LocalPostgresWriter(ctx, dsn)
        try:
            batch_ctx = DestinationBatchContext(run=ctx, batch_index=0, is_final_batch=True)
            await writer.write_batch(_batches(_rows(["a", "b"], [1, 2])), batch_ctx)
            # A crash after the write but before the state was recorded re-claims this batch.
            await writer.write_batch(_batches(_rows(["a", "b"], [1, 2])), batch_ctx)
            await writer.finalize_run(ctx)

            assert _read(dsn, table_name) == [(1, "a"), (2, "b")]
        finally:
            _drop(dsn, table_name, staging_table_name(ctx))

    async def test_finalizing_twice_leaves_the_swapped_table_alone(self, dsn, table_name) -> None:
        # The consumer re-claims a final batch whose outcome it could not confirm, so the swap
        # has to survive being asked for again.
        ctx = _ctx(table_name, "full_refresh")
        writer = LocalPostgresWriter(ctx, dsn)
        try:
            await writer.write_batch(
                _batches(_rows(["a"], [1])),
                DestinationBatchContext(run=ctx, batch_index=0, is_final_batch=True),
            )
            await writer.finalize_run(ctx)
            await writer.finalize_run(ctx)

            assert _read(dsn, table_name) == [(1, "a")]
        finally:
            _drop(dsn, table_name, staging_table_name(ctx))

    async def test_a_run_that_never_finishes_leaves_the_previous_data_in_place(self, dsn, table_name) -> None:
        first = _ctx(table_name, "full_refresh")
        first_writer = LocalPostgresWriter(first, dsn)
        second = _ctx(table_name, "full_refresh")
        second_writer = LocalPostgresWriter(second, dsn)
        try:
            await first_writer.write_batch(
                _batches(_rows(["old"], [1])),
                DestinationBatchContext(run=first, batch_index=0, is_final_batch=True),
            )
            await first_writer.finalize_run(first)

            # A second run writes a batch and then dies before finalizing.
            await second_writer.write_batch(
                _batches(_rows(["new"], [2])),
                DestinationBatchContext(run=second, batch_index=0, is_final_batch=False),
            )
            await second_writer.abort_run(second)

            assert _read(dsn, table_name) == [(1, "old")]
        finally:
            _drop(dsn, table_name, staging_table_name(first), staging_table_name(second))


class TestIncremental:
    async def test_rows_are_merged_on_the_primary_key(self, dsn, table_name) -> None:
        ctx = _ctx(table_name, "incremental", primary_keys=("id",))
        writer = LocalPostgresWriter(ctx, dsn)
        try:
            await writer.write_batch(
                _batches(_rows(["first", "second"], [1, 2])),
                DestinationBatchContext(run=ctx, batch_index=0, is_final_batch=False),
            )
            await writer.write_batch(
                _batches(_rows(["updated"], [1])),
                DestinationBatchContext(run=ctx, batch_index=1, is_final_batch=True),
            )
            await writer.finalize_run(ctx)

            assert _read(dsn, table_name) == [(1, "updated"), (2, "second")]
        finally:
            _drop(dsn, table_name)

    async def test_reapplying_a_batch_is_harmless(self, dsn, table_name) -> None:
        ctx = _ctx(table_name, "incremental", primary_keys=("id",))
        writer = LocalPostgresWriter(ctx, dsn)
        try:
            batch_ctx = DestinationBatchContext(run=ctx, batch_index=0, is_final_batch=True)
            await writer.write_batch(_batches(_rows(["a"], [1])), batch_ctx)
            await writer.write_batch(_batches(_rows(["a"], [1])), batch_ctx)

            assert _read(dsn, table_name) == [(1, "a")]
        finally:
            _drop(dsn, table_name)

    async def test_a_new_source_column_is_added_rather_than_dropped(self, dsn, table_name) -> None:
        ctx = _ctx(table_name, "incremental", primary_keys=("id",))
        writer = LocalPostgresWriter(ctx, dsn)
        try:
            await writer.write_batch(
                _batches(_rows(["a"], [1])),
                DestinationBatchContext(run=ctx, batch_index=0, is_final_batch=False),
            )
            widened = pa.RecordBatch.from_pydict({"id": [2], "name": ["b"], "extra": ["kept"]})
            await writer.write_batch(
                _batches(widened),
                DestinationBatchContext(run=ctx, batch_index=1, is_final_batch=True),
            )

            with psycopg.connect(dsn, autocommit=True) as conn:
                rows = conn.execute(f'SELECT id, extra FROM public."{table_name}" ORDER BY id').fetchall()
            assert rows == [(1, None), (2, "kept")]
        finally:
            _drop(dsn, table_name)
