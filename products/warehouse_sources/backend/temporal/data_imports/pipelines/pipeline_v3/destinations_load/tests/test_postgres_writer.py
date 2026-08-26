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
    _OWNERSHIP_COMMENT,
    PostgresDestinationWriter,
    UnrelatedTableExistsError,
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


class TestFullRefreshTableOwnership:
    """`table_name` is derived from the source's resource name, which a custom-source
    manifest controls. A full refresh must never take over a table it did not create just
    because a resource happens to be named after it.
    """

    async def test_a_full_refresh_refuses_to_replace_a_table_it_did_not_create(self, dsn, table_name) -> None:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'CREATE TABLE public."{table_name}" (id BIGINT, name TEXT)')
            conn.execute(f"INSERT INTO public.\"{table_name}\" VALUES (99, 'untouched')")

        ctx = _ctx(table_name, "full_refresh")
        writer = LocalPostgresWriter(ctx, dsn)
        try:
            await writer.write_batch(
                _batches(_rows(["a"], [1])),
                DestinationBatchContext(run=ctx, batch_index=0, is_final_batch=True),
            )

            with pytest.raises(UnrelatedTableExistsError):
                await writer.finalize_run(ctx)

            # The pre-existing table was never touched, and the staging table is still there
            # for a retry to pick up once the name collision is resolved.
            assert _read(dsn, table_name) == [(99, "untouched")]
        finally:
            _drop(dsn, table_name, staging_table_name(ctx))

    async def test_a_second_full_refresh_may_replace_a_table_the_first_one_created(self, dsn, table_name) -> None:
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

            await second_writer.write_batch(
                _batches(_rows(["new"], [2])),
                DestinationBatchContext(run=second, batch_index=0, is_final_batch=True),
            )
            await second_writer.finalize_run(second)

            assert _read(dsn, table_name) == [(2, "new")]
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


class TestIncrementalTableOwnership:
    """An incremental run writes straight into the live table, named after the source's
    resource name. It must refuse a table it did not create, the same way a full refresh
    refuses to replace one, rather than evolving its schema and merging rows into it.
    """

    async def test_an_incremental_run_refuses_to_write_into_a_table_it_did_not_create(self, dsn, table_name) -> None:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'CREATE TABLE public."{table_name}" (id BIGINT, name TEXT)')
            conn.execute(f"INSERT INTO public.\"{table_name}\" VALUES (99, 'untouched')")

        ctx = _ctx(table_name, "incremental", primary_keys=("id",))
        writer = LocalPostgresWriter(ctx, dsn)
        try:
            with pytest.raises(UnrelatedTableExistsError):
                await writer.write_batch(
                    _batches(_rows(["a"], [1])),
                    DestinationBatchContext(run=ctx, batch_index=0, is_final_batch=True),
                )

            # Neither the table's schema nor its rows were touched.
            assert _read(dsn, table_name) == [(99, "untouched")]
        finally:
            _drop(dsn, table_name)

    async def test_a_later_incremental_run_may_write_into_a_table_this_writer_created(self, dsn, table_name) -> None:
        first = _ctx(table_name, "incremental", primary_keys=("id",))
        first_writer = LocalPostgresWriter(first, dsn)
        second = _ctx(table_name, "incremental", primary_keys=("id",))
        second_writer = LocalPostgresWriter(second, dsn)
        try:
            await first_writer.write_batch(
                _batches(_rows(["a"], [1])),
                DestinationBatchContext(run=first, batch_index=0, is_final_batch=True),
            )
            await second_writer.write_batch(
                _batches(_rows(["b"], [2])),
                DestinationBatchContext(run=second, batch_index=0, is_final_batch=True),
            )

            assert _read(dsn, table_name) == [(1, "a"), (2, "b")]
        finally:
            _drop(dsn, table_name)


class TestValueFidelity:
    async def test_values_holding_csv_control_characters_survive_the_copy(self, dsn, table_name) -> None:
        # The bulk load is a COPY in CSV format, where a tab ends a field and a newline ends a
        # row unless the value is quoted.
        awkward = ["a\tb", "line\nbreak", 'say "hi"', "back\\slash", "", "  padded  "]
        ctx = _ctx(table_name, "full_refresh")
        writer = LocalPostgresWriter(ctx, dsn)
        try:
            batch = pa.RecordBatch.from_pydict(
                {"id": list(range(len(awkward) + 1)), "name": [*awkward, None]},
            )
            await writer.write_batch(
                _batches(batch),
                DestinationBatchContext(run=ctx, batch_index=0, is_final_batch=True),
            )
            await writer.finalize_run(ctx)

            assert _read(dsn, table_name) == [*enumerate(awkward), (len(awkward), None)]
        finally:
            _drop(dsn, table_name, staging_table_name(ctx))

    async def test_nested_values_land_in_their_json_columns(self, dsn, table_name) -> None:
        # Lists, structs and maps all map onto JSONB, which rejects both a Postgres array
        # literal and a Python repr.
        ctx = _ctx(table_name, "full_refresh")
        writer = LocalPostgresWriter(ctx, dsn)
        try:
            batch = pa.RecordBatch.from_arrays(
                [
                    pa.array([1, 2], type=pa.int64()),
                    pa.array([["a", "b"], None], type=pa.list_(pa.string())),
                    pa.array([{"k": "v", "n": 3}, None], type=pa.struct([("k", pa.string()), ("n", pa.int64())])),
                    pa.array([[("x", 1)], None], type=pa.map_(pa.string(), pa.int64())),
                ],
                names=["id", "tags", "meta", "labels"],
            )
            await writer.write_batch(
                _batches(batch),
                DestinationBatchContext(run=ctx, batch_index=0, is_final_batch=True),
            )
            await writer.finalize_run(ctx)

            with psycopg.connect(dsn, autocommit=True) as conn:
                rows = conn.execute(f'SELECT id, tags, meta, labels FROM public."{table_name}" ORDER BY id').fetchall()

            assert rows == [
                (1, ["a", "b"], {"k": "v", "n": 3}, {"x": 1}),
                (2, None, None, None),
            ]
        finally:
            _drop(dsn, table_name, staging_table_name(ctx))

    async def test_a_nested_value_holding_a_delimiter_still_parses_as_json(self, dsn, table_name) -> None:
        # The JSON text goes through the same CSV writer, so a tab or a quote inside a struct
        # has to be quoted on the way out and parsed as JSON on the way in.
        ctx = _ctx(table_name, "full_refresh")
        writer = LocalPostgresWriter(ctx, dsn)
        try:
            batch = pa.RecordBatch.from_arrays(
                [
                    pa.array([1], type=pa.int64()),
                    pa.array(
                        [{"note": 'has\ta tab, a "quote" and a\nnewline'}],
                        type=pa.struct([("note", pa.string())]),
                    ),
                ],
                names=["id", "meta"],
            )
            await writer.write_batch(
                _batches(batch),
                DestinationBatchContext(run=ctx, batch_index=0, is_final_batch=True),
            )
            await writer.finalize_run(ctx)

            with psycopg.connect(dsn, autocommit=True) as conn:
                rows = conn.execute(f'SELECT meta FROM public."{table_name}"').fetchall()

            assert rows == [({"note": 'has\ta tab, a "quote" and a\nnewline'},)]
        finally:
            _drop(dsn, table_name, staging_table_name(ctx))


class TestMergeConstraints:
    """The merge target's unique constraint, which `ON CONFLICT` needs to exist."""

    @staticmethod
    def _unique_indexes(dsn: str, table: str) -> list[tuple[str, list[str]]]:
        with psycopg.connect(dsn, autocommit=True) as conn:
            rows = conn.execute(
                """
                SELECT ic.relname::text, array_agg(a.attname::text ORDER BY a.attname)
                FROM pg_index i
                JOIN pg_class c ON c.oid = i.indrelid
                JOIN pg_class ic ON ic.oid = i.indexrelid
                JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY (i.indkey)
                WHERE i.indisunique AND c.relname = %s
                GROUP BY ic.relname
                """,
                (table,),
            ).fetchall()
        return [(name, cols) for name, cols in rows]

    async def test_the_merge_target_is_created_with_its_primary_key(self, dsn, table_name) -> None:
        # Declared at creation by acreate_table rather than added as a separate index, so the
        # table carries exactly one unique constraint over the merge keys.
        ctx = _ctx(table_name, "incremental", primary_keys=("id",))
        writer = LocalPostgresWriter(ctx, dsn)
        try:
            await writer.write_batch(
                _batches(_rows(["a"], [1])),
                DestinationBatchContext(run=ctx, batch_index=0, is_final_batch=True),
            )

            indexes = self._unique_indexes(dsn, table_name)
            assert [cols for _, cols in indexes] == [["id"]], indexes
        finally:
            _drop(dsn, table_name)

    async def test_a_table_the_customer_already_had_gains_one(self, dsn, table_name) -> None:
        # This writer created the table on an earlier run, before unique index enforcement
        # existed, so it carries the ownership comment but no key. Nothing declared a key on
        # this table, so the writer has to add one before it can merge into it.
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'CREATE TABLE "{table_name}" (id BIGINT, name TEXT)')
            conn.execute(f"COMMENT ON TABLE \"{table_name}\" IS '{_OWNERSHIP_COMMENT}'")

        ctx = _ctx(table_name, "incremental", primary_keys=("id",))
        writer = LocalPostgresWriter(ctx, dsn)
        try:
            await writer.write_batch(
                _batches(_rows(["a"], [1])),
                DestinationBatchContext(run=ctx, batch_index=0, is_final_batch=True),
            )

            assert [cols for _, cols in self._unique_indexes(dsn, table_name)] == [["id"]]
            assert _read(dsn, table_name) == [(1, "a")]
        finally:
            _drop(dsn, table_name)

    async def test_merging_many_batches_does_not_accumulate_indexes(self, dsn, table_name) -> None:
        # The index step runs per merged batch. It used to CREATE ... IF NOT EXISTS, which
        # matches on name, so a declared primary key would sit beside a duplicate of itself.
        ctx = _ctx(table_name, "incremental", primary_keys=("id",))
        writer = LocalPostgresWriter(ctx, dsn)
        try:
            for index in range(3):
                await writer.write_batch(
                    _batches(_rows(["a"], [index])),
                    DestinationBatchContext(run=ctx, batch_index=index, is_final_batch=index == 2),
                )

            assert len(self._unique_indexes(dsn, table_name)) == 1
        finally:
            _drop(dsn, table_name)
