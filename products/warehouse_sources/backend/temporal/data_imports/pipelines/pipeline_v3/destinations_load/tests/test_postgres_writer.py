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
    UnrelatedTableExistsError,
    _owned_marker,
    _scoped_identifier,
    merge_stage_name,
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


def _ctx(
    table_name: str, sync_type: str, primary_keys: tuple[str, ...] = (), schema_id: str = "schema"
) -> DestinationRunContext:
    return DestinationRunContext(
        team_id=1,
        schema_id=schema_id,
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


def _table_exists(dsn: str, table: str) -> bool:
    with psycopg.connect(dsn, autocommit=True) as conn:
        return (
            conn.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s",
                (table,),
            ).fetchone()
            is not None
        )


def _row_count(dsn: str, table: str) -> int:
    with psycopg.connect(dsn, autocommit=True) as conn:
        return conn.execute(f'SELECT count(*) FROM public."{table}"').fetchone()[0]


def _drop(dsn: str, *tables: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        for table in tables:
            conn.execute(f'DROP TABLE IF EXISTS public."{table}" CASCADE')


class TestStagingTableNameTruncation:
    """Postgres silently truncates any identifier past 63 bytes. The run-scoped suffix has to
    survive that truncation itself, or a long enough `table_name` collapses the staging name
    back onto a name Postgres would treat identically to the live table's own (also
    truncated) name.
    """

    async def test_a_short_table_name_is_untouched(self) -> None:
        ctx = _ctx("orders", "full_refresh")
        name = staging_table_name(ctx)

        assert name.startswith("orders__ph_stage_")
        assert len(name.encode()) <= 63

    async def test_a_long_table_name_still_ends_with_its_full_run_suffix(self) -> None:
        ctx = _ctx("r" * 100, "full_refresh")
        name = staging_table_name(ctx)
        suffix = f"__ph_stage_{ctx.run_uuid.replace('-', '')[:12]}"

        # The whole point: Postgres's own truncation drops the *end* of an over-length
        # identifier first, which is exactly this suffix. Truncating the base ourselves means
        # the suffix is always what's left, not what's cut.
        assert name.endswith(suffix)
        assert len(name.encode()) <= 63

    async def test_two_long_table_names_sharing_a_63_byte_prefix_still_differ(self) -> None:
        # What an attacker actually needs for the identifier-truncation attack: two
        # `table_name`s identical for the first 63 bytes (what Postgres alone would leave
        # standing) but different beyond it.
        first = _ctx("r" * 100 + "-one", "full_refresh")
        second = _ctx("r" * 100 + "-two", "full_refresh")

        assert staging_table_name(first) != staging_table_name(second)

    async def test_a_multibyte_table_name_does_not_raise(self) -> None:
        ctx = _ctx("é" * 60, "full_refresh")
        name = staging_table_name(ctx)

        assert len(name.encode()) <= 63


class TestScopedIdentifierTruncation:
    """`_scoped_identifier` is what `staging_table_name` above is built on, and also what an
    incremental merge's per-batch stage table and unique index names are built on. Unlike a
    full refresh's staging name, an incremental `target` is never itself truncated by this
    writer, so it can already sit at Postgres's 63-byte limit before a suffix is even added.
    """

    def test_a_short_base_is_untouched(self) -> None:
        name = _scoped_identifier("orders", "__ph_merge_abcd1234")

        assert name == "orders__ph_merge_abcd1234"

    def test_a_63_byte_base_still_gets_a_distinct_suffixed_name(self) -> None:
        # The exact shape of the bug: `target` is already at the limit a merge stage or index
        # name would otherwise collapse onto if its suffix were left for Postgres to truncate.
        base = "t" * 63
        stage = _scoped_identifier(base, "__ph_merge_abcd1234")
        index = _scoped_identifier(base, "__ph_pk")

        assert stage != base
        assert index != base
        assert stage != index
        assert len(stage.encode()) <= 63
        assert len(index.encode()) <= 63
        assert stage.endswith("__ph_merge_abcd1234")
        assert index.endswith("__ph_pk")

    def test_a_far_longer_base_still_yields_a_distinct_suffixed_name(self) -> None:
        base = "t" * 200
        stage = _scoped_identifier(base, "__ph_merge_abcd1234")

        assert stage != base.encode()[:63].decode()
        assert stage.endswith("__ph_merge_abcd1234")
        assert len(stage.encode()) <= 63


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

    async def test_replaying_the_published_final_batch_keeps_the_earlier_batches(self, dsn, table_name) -> None:
        # Without the publish stamp this replays as "write one batch into a fresh staging
        # table, then swap it over the finished table", leaving only the final batch's rows.
        # Reachable whenever the write marker is missing: Redis down, or a crash between the
        # swap and the marker.
        ctx = _ctx(table_name, "full_refresh")
        writer = LocalPostgresWriter(ctx, dsn)
        try:
            await writer.write_batch(
                _batches(_rows(["a", "b"], [1, 2])),
                DestinationBatchContext(run=ctx, batch_index=0, is_final_batch=False),
            )
            final_ctx = DestinationBatchContext(run=ctx, batch_index=1, is_final_batch=True)
            await writer.write_batch(_batches(_rows(["c"], [3])), final_ctx)
            await writer.finalize_run(ctx)
            assert _read(dsn, table_name) == [(1, "a"), (2, "b"), (3, "c")]

            await writer.write_batch(_batches(_rows(["c"], [3])), final_ctx)
            await writer.finalize_run(ctx)

            assert _read(dsn, table_name) == [(1, "a"), (2, "b"), (3, "c")]
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

    async def test_a_full_refresh_refuses_to_reuse_an_existing_table_as_staging(self, dsn, table_name) -> None:
        """Guards the staging table itself, not just the final swap target.

        Before the ownership check on `write_batch`'s first batch existed, an identifier
        collision (see `TestStagingTableNameTruncation`) or any other reason a table already
        sat at the generated staging name would have this writer adopt it silently: evolve
        its schema, delete rows matching this run's batch index, and stamp its own ownership
        marker over whatever was there — all before `finalize_run` ever got a chance to check
        anything.
        """
        ctx = _ctx(table_name, "full_refresh")
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'CREATE TABLE public."{staging_table_name(ctx)}" (id BIGINT, name TEXT)')
            conn.execute(f"INSERT INTO public.\"{staging_table_name(ctx)}\" VALUES (99, 'untouched')")

        writer = LocalPostgresWriter(ctx, dsn)
        try:
            with pytest.raises(UnrelatedTableExistsError):
                await writer.write_batch(
                    _batches(_rows(["a"], [1])),
                    DestinationBatchContext(run=ctx, batch_index=0, is_final_batch=True),
                )

            # Neither the pre-existing table's schema nor its rows were touched.
            with psycopg.connect(dsn, autocommit=True) as conn:
                rows = conn.execute(f'SELECT id, name FROM public."{staging_table_name(ctx)}" ORDER BY id').fetchall()
            assert rows == [(99, "untouched")]
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
    async def test_batches_share_one_merge_stage_that_finalize_drops(self, dsn, table_name) -> None:
        # A stage table per batch writes catalog rows a customer's server then has to vacuum,
        # so the run keeps one and empties it between batches.
        ctx = _ctx(table_name, "incremental", primary_keys=("id",))
        writer = LocalPostgresWriter(ctx, dsn)
        stage = merge_stage_name(table_name, ctx)
        try:
            await writer.write_batch(
                _batches(_rows(["a"], [1])),
                DestinationBatchContext(run=ctx, batch_index=0, is_final_batch=False),
            )
            assert _table_exists(dsn, stage)

            await writer.write_batch(
                _batches(_rows(["b"], [2])),
                DestinationBatchContext(run=ctx, batch_index=1, is_final_batch=True),
            )
            # Emptied between batches, so it never accumulates the run's rows.
            assert _row_count(dsn, stage) == 1
            assert _read(dsn, table_name) == [(1, "a"), (2, "b")]

            await writer.finalize_run(ctx)
            assert not _table_exists(dsn, stage)
        finally:
            _drop(dsn, table_name, stage)

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

    async def test_a_table_name_already_at_the_identifier_limit_still_merges_correctly(self, dsn) -> None:
        """Regression test for the merge-stage aliasing bug: an incremental run's live table
        name is never truncated by this writer (unlike a full refresh's staging name), so it
        can already sit at Postgres's 63-byte limit on its own. Each batch's merge stage must
        still get a name distinct from it, or `_merge_stage`'s `delete=True` drops the live
        table out from under the run instead of just its own short-lived stage.
        """
        long_name = "t" * 70
        actual_table = long_name.encode()[:63].decode()
        ctx = _ctx(long_name, "incremental", primary_keys=("id",))
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

            assert _read(dsn, actual_table) == [(1, "updated"), (2, "second")]
        finally:
            _drop(dsn, actual_table)


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


class TestCrossSchemaTableOwnership:
    """`table_name` is derived from the editable resource name, so two different schemas can
    choose the same target name on the same destination. Ownership must be scoped to the
    schema that created the table, not just "some posthog warehouse sync created this", or one
    schema's resource could pass as the owner of another schema's table.
    """

    async def test_a_full_refresh_refuses_to_replace_a_table_a_different_schema_created(self, dsn, table_name) -> None:
        first = _ctx(table_name, "full_refresh", schema_id="schema-a")
        first_writer = LocalPostgresWriter(first, dsn)
        second = _ctx(table_name, "full_refresh", schema_id="schema-b")
        second_writer = LocalPostgresWriter(second, dsn)
        try:
            await first_writer.write_batch(
                _batches(_rows(["a"], [1])),
                DestinationBatchContext(run=first, batch_index=0, is_final_batch=True),
            )
            await first_writer.finalize_run(first)

            await second_writer.write_batch(
                _batches(_rows(["b"], [2])),
                DestinationBatchContext(run=second, batch_index=0, is_final_batch=True),
            )

            with pytest.raises(UnrelatedTableExistsError):
                await second_writer.finalize_run(second)

            # The first schema's table is exactly as that schema's run left it.
            assert _read(dsn, table_name) == [(1, "a")]
        finally:
            _drop(dsn, table_name, staging_table_name(first), staging_table_name(second))

    async def test_an_incremental_run_refuses_to_write_into_a_table_a_different_schema_created(
        self, dsn, table_name
    ) -> None:
        first = _ctx(table_name, "incremental", primary_keys=("id",), schema_id="schema-a")
        first_writer = LocalPostgresWriter(first, dsn)
        second = _ctx(table_name, "incremental", primary_keys=("id",), schema_id="schema-b")
        second_writer = LocalPostgresWriter(second, dsn)
        try:
            await first_writer.write_batch(
                _batches(_rows(["a"], [1])),
                DestinationBatchContext(run=first, batch_index=0, is_final_batch=True),
            )

            with pytest.raises(UnrelatedTableExistsError):
                await second_writer.write_batch(
                    _batches(_rows(["b"], [2])),
                    DestinationBatchContext(run=second, batch_index=0, is_final_batch=True),
                )

            assert _read(dsn, table_name) == [(1, "a")]
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
            conn.execute(f"COMMENT ON TABLE \"{table_name}\" IS '{_owned_marker('schema')}'")

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
