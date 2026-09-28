from collections.abc import AsyncIterator

import pytest

import pyarrow as pa
from parameterized import parameterized

from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import SnowflakeClient
from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import (
    DestinationBatchContext,
    DestinationRunContext,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.tests.fake_snowflake import (
    FakeSnowflakeClient,
    FakeSnowflakeTable,
    MergeMultiMatchError,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.snowflake import (
    SnowflakeDestinationWriter,
    UnrelatedTableExistsError,
    merge_stage_name,
    stage_prefix,
    staging_table_name,
)

pytestmark = pytest.mark.asyncio


class LocalSnowflakeWriter(SnowflakeDestinationWriter):
    """Points the writer at an in-memory Snowflake instead of a customer's account."""

    def __init__(self, ctx: DestinationRunContext, client: FakeSnowflakeClient) -> None:
        super().__init__(ctx)
        self._fake = client

    async def _make_client(self) -> SnowflakeClient:
        return self._fake  # type: ignore[return-value]  # ty: ignore[invalid-return-type]


async def _batches(*record_batches: pa.RecordBatch) -> AsyncIterator[pa.RecordBatch]:
    for batch in record_batches:
        yield batch


def _rows(ids: list[int], names: list[str]) -> pa.RecordBatch:
    return pa.RecordBatch.from_pydict({"id": ids, "name": names})


def _ctx(
    sync_type: str = "full_refresh",
    primary_keys: tuple[str, ...] = (),
    run_uuid: str = "run-a1",
    schema_id: str = "schema",
    config: dict | None = None,
) -> DestinationRunContext:
    return DestinationRunContext(
        team_id=1,
        schema_id=schema_id,
        source_id="source",
        job_id="job",
        run_uuid=run_uuid,
        destination_id="destination",
        destination_type="Snowflake",
        destination_name="test snowflake",
        table_name="charges",
        sync_type=sync_type,
        primary_keys=primary_keys,
        config=config if config is not None else {"database": "DB", "schema": "PUBLIC", "warehouse": "WH"},
    )


def _read(client: FakeSnowflakeClient, table: str = "charges") -> list[tuple]:
    return sorted((row["id"], row["name"]) for row in client.tables[table].rows)


async def _deliver(
    writer: SnowflakeDestinationWriter,
    ctx: DestinationRunContext,
    batch: pa.RecordBatch,
    batch_index: int,
    *,
    is_final: bool = False,
) -> None:
    await writer.write_batch(
        _batches(batch), DestinationBatchContext(run=ctx, batch_index=batch_index, is_final_batch=is_final)
    )
    if is_final:
        await writer.finalize_run(ctx)


class TestFullRefresh:
    async def test_the_live_table_only_changes_once_the_run_completes(self) -> None:
        client = FakeSnowflakeClient()
        ctx = _ctx()
        writer = LocalSnowflakeWriter(ctx, client)

        await _deliver(writer, ctx, _rows([1], ["a"]), 0)
        assert "charges" not in client.tables

        await _deliver(writer, ctx, _rows([2], ["b"]), 1, is_final=True)

        assert _read(client) == [(1, "a"), (2, "b")]

    async def test_reapplying_a_batch_does_not_duplicate_its_rows(self) -> None:
        client = FakeSnowflakeClient()
        ctx = _ctx()
        writer = LocalSnowflakeWriter(ctx, client)

        batch = _rows([1, 2], ["a", "b"])
        await _deliver(writer, ctx, batch, 0)
        # A crash after the write but before the state was recorded re-claims this batch.
        await _deliver(writer, ctx, batch, 0, is_final=True)

        assert _read(client) == [(1, "a"), (2, "b")]

    async def test_replaying_the_published_final_batch_keeps_the_earlier_batches(self) -> None:
        # Without the publish stamp this replays as "rebuild a staging table from one batch,
        # then swap it over the finished table", leaving only the final batch's rows. Reachable
        # whenever the write marker is missing: Redis down, or a crash between the swap and the
        # marker.
        client = FakeSnowflakeClient()
        ctx = _ctx()
        writer = LocalSnowflakeWriter(ctx, client)

        await _deliver(writer, ctx, _rows([1, 2], ["a", "b"]), 0)
        await _deliver(writer, ctx, _rows([3], ["c"]), 1, is_final=True)
        assert _read(client) == [(1, "a"), (2, "b"), (3, "c")]

        await _deliver(writer, ctx, _rows([3], ["c"]), 1, is_final=True)

        assert _read(client) == [(1, "a"), (2, "b"), (3, "c")]

    async def test_the_published_table_does_not_carry_the_batch_index_column(self) -> None:
        client = FakeSnowflakeClient()
        ctx = _ctx()

        await _deliver(LocalSnowflakeWriter(ctx, client), ctx, _rows([1], ["a"]), 0, is_final=True)

        assert client.tables["charges"].columns == ["id", "name"]

    async def test_a_second_full_refresh_may_replace_a_table_the_first_one_created(self) -> None:
        # The table the first run published carries its publish stamp, and the ownership check
        # has to keep reading that as "owned by this schema" or no later run could ever publish.
        client = FakeSnowflakeClient()
        first = _ctx(run_uuid="run-a1")
        second = _ctx(run_uuid="run-b2")

        await _deliver(LocalSnowflakeWriter(first, client), first, _rows([1], ["old"]), 0, is_final=True)
        await _deliver(LocalSnowflakeWriter(second, client), second, _rows([2], ["new"]), 0, is_final=True)

        assert _read(client) == [(2, "new")]

    async def test_a_full_refresh_refuses_to_replace_a_table_a_different_schema_created(self) -> None:
        client = FakeSnowflakeClient()
        first = _ctx(schema_id="schema-a", run_uuid="run-a1")
        second = _ctx(schema_id="schema-b", run_uuid="run-b2")

        await _deliver(LocalSnowflakeWriter(first, client), first, _rows([1], ["a"]), 0, is_final=True)

        second_writer = LocalSnowflakeWriter(second, client)
        await _deliver(second_writer, second, _rows([2], ["b"]), 0)
        with pytest.raises(UnrelatedTableExistsError):
            await second_writer.finalize_run(second)

        assert _read(client) == [(1, "a")]


class TestIncremental:
    async def test_rows_are_merged_on_the_primary_key(self) -> None:
        client = FakeSnowflakeClient()
        ctx = _ctx(sync_type="incremental", primary_keys=("id",))
        writer = LocalSnowflakeWriter(ctx, client)

        await _deliver(writer, ctx, _rows([1, 2], ["first", "second"]), 0)
        await _deliver(writer, ctx, _rows([1], ["updated"]), 1, is_final=True)

        assert _read(client) == [(1, "updated"), (2, "second")]

    async def test_a_batch_carrying_one_key_twice_keeps_the_last_row(self) -> None:
        # Nothing upstream promises a staged batch holds each key once, and Snowflake rejects a
        # MERGE whose source matches a target row more than once, on every retry.
        client = FakeSnowflakeClient()
        ctx = _ctx(sync_type="incremental", primary_keys=("id",))
        writer = LocalSnowflakeWriter(ctx, client)

        await _deliver(writer, ctx, _rows([1], ["first"]), 0)
        await _deliver(writer, ctx, _rows([1, 1], ["stale", "latest"]), 1, is_final=True)

        assert _read(client) == [(1, "latest")]

    async def test_the_fake_rejects_a_duplicated_key_the_way_snowflake_does(self) -> None:
        # Guards the test above: if the fake accepted a multi-matching MERGE, that test would
        # pass with or without the dedup.
        client = FakeSnowflakeClient()
        client.tables["charges"] = FakeSnowflakeTable(["id", "name"])
        client.tables["charges"].rows = [{"id": 1, "name": "first"}]
        client.tables["stage"] = FakeSnowflakeTable(["id", "name"])
        client.tables["stage"].rows = [{"id": 1, "name": "stale"}, {"id": 1, "name": "latest"}]

        with pytest.raises(MergeMultiMatchError):
            await client.execute_async_query(
                'MERGE INTO "PUBLIC"."charges" AS target USING "PUBLIC"."stage" AS source '
                'ON target."id" = source."id" '
                'WHEN MATCHED THEN UPDATE SET target."name" = source."name" '
                'WHEN NOT MATCHED THEN INSERT ("id", "name") VALUES (source."id", source."name")'
            )


class TestRunScopedScratchNames:
    """Two runs of one table's incremental sync can be in flight together, because this writer
    does not hold the sync lock. They share the live table, and therefore its internal stage, so
    a scratch name that only carries the batch index collides: one run's stage cleanup deletes
    the file the other just uploaded, and one run's `DROP TABLE` drops the merge source the
    other is reading.
    """

    @parameterized.expand(
        [
            ("stage file path", lambda run_uuid: stage_prefix(run_uuid, 0, 0)),
            ("merge scratch table", lambda run_uuid: merge_stage_name("charges", run_uuid, 0, 0)),
            ("staging table", lambda run_uuid: staging_table_name(_ctx(run_uuid=run_uuid))),
        ]
    )
    def test_two_runs_of_the_same_table_and_batch_get_different_names(self, _name, name_for) -> None:
        assert name_for("3f8c1d2e-aaaa-4000-8000-000000000001") != name_for("9b2d4e6f-bbbb-4000-8000-000000000002")


class TestIdentifierSafety:
    """`SnowflakeClient` interpolates these four straight into `USE ...` statements with no
    escaping of its own, and a destination's config is editable.
    """

    @parameterized.expand(
        [
            ("database", {"database": 'DB" -- ', "schema": "PUBLIC", "warehouse": "WH"}),
            ("schema", {"database": "DB", "schema": 'PUBLIC"', "warehouse": "WH"}),
            ("warehouse", {"database": "DB", "schema": "PUBLIC", "warehouse": "WH\n"}),
            ("role", {"database": "DB", "schema": "PUBLIC", "warehouse": "WH", "role": 'R"'}),
            ("missing database", {"schema": "PUBLIC", "warehouse": "WH"}),
            ("missing warehouse", {"database": "DB", "schema": "PUBLIC"}),
        ]
    )
    def test_a_config_that_could_break_out_of_its_quoting_is_rejected(self, _name, config) -> None:
        with pytest.raises(ValueError):
            SnowflakeDestinationWriter(_ctx(config=config))

    def test_an_unset_role_is_allowed(self) -> None:
        # Snowflake falls back to the user's default role, so no role is a valid config.
        writer = SnowflakeDestinationWriter(_ctx(config={"database": "DB", "schema": "PUBLIC", "warehouse": "WH"}))

        assert writer._role is None
