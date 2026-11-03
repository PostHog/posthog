from collections.abc import AsyncIterator
from dataclasses import replace

import pytest
from unittest import mock

import pyarrow as pa
from parameterized import parameterized
from snowflake.connector.errors import OperationalError, ProgrammingError

from products.batch_exports.backend.facade.destinations.snowflake import (
    InvalidPrivateKeyError,
    SnowflakeAuthenticationError,
    SnowflakeClient,
    SnowflakeConnectionError,
    SnowflakeFileNotLoadedError,
    SnowflakeIncompatibleSchemaError,
    SnowflakeInsufficientPrivilegesError,
    SnowflakeIntegrationNotFoundError,
    SnowflakeQueryClientTimeoutError,
    SnowflakeQueryServerTimeoutError,
    SnowflakeRetryableConnectionError,
    SnowflakeWarehouseSuspendedError,
    SnowflakeWarehouseUsageError,
)
from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import (
    DestinationBatchContext,
    DestinationRunContext,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.errors import (
    MISSING_INTEGRATION_DETAIL,
    DestinationConfigurationError,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.tests.fake_snowflake import (
    FakeSnowflakeClient,
    FakeSnowflakeTable,
    MergeMultiMatchError,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers import (
    snowflake,
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


class TestConfigurationErrors:
    @pytest.mark.parametrize("finalize", [False, True], ids=["write_batch", "finalize_run"])
    @pytest.mark.parametrize(
        ("error", "detail_word"),
        [
            (SnowflakeAuthenticationError("fake-secret"), "password"),
            (InvalidPrivateKeyError("fake-secret"), "private key"),
            (SnowflakeConnectionError("fake-secret"), "account"),
            (SnowflakeInsufficientPrivilegesError("fake-secret"), "privileges"),
            (SnowflakeWarehouseUsageError("fake-secret"), "warehouse"),
            (SnowflakeIntegrationNotFoundError(42, 1), "connection details"),
            (ProgrammingError(msg="fake-secret", errno=3001), "privileges"),
            (ProgrammingError(msg="fake-secret", errno=2043), "database or schema"),
            (ProgrammingError(msg="fake-secret", errno=666), "suspended"),
        ],
    )
    async def test_permanent_errors_are_configuration_errors(
        self, error: Exception, detail_word: str, finalize: bool
    ) -> None:
        ctx = _ctx()
        client = FakeSnowflakeClient()
        writer = LocalSnowflakeWriter(ctx, client)
        target = client if isinstance(error, ProgrammingError) else writer
        method = "execute_async_query" if isinstance(error, ProgrammingError) else "_make_client"

        with (
            mock.patch.object(target, method, side_effect=error),
            pytest.raises(DestinationConfigurationError, match=detail_word) as caught,
        ):
            if finalize:
                await writer.finalize_run(ctx)
            else:
                await writer.write_batch(
                    _batches(_rows([1], ["a"])), DestinationBatchContext(run=ctx, batch_index=0, is_final_batch=False)
                )

        assert str(caught.value).startswith(f"{ctx.destination_name}:")
        assert caught.value.__cause__ is error
        assert str(error) not in caught.value.detail
        assert "fake-secret" not in caught.value.detail

    @pytest.mark.parametrize("finalize", [False, True], ids=["write_batch", "finalize_run"])
    @pytest.mark.parametrize(
        "error",
        [
            SnowflakeRetryableConnectionError("fake-secret"),
            SnowflakeWarehouseSuspendedError("fake-secret"),
            SnowflakeQueryClientTimeoutError(1, "fake-secret", "RUNNING"),
            SnowflakeQueryServerTimeoutError("fake-secret"),
            SnowflakeFileNotLoadedError("charges", "FAILED", 1, "fake-secret"),
            SnowflakeIncompatibleSchemaError("fake-secret"),
            ProgrammingError(msg="fake-secret", errno=608),
            ProgrammingError(msg="fake-secret", errno=90073),
            OperationalError(msg="fake-secret"),
            TimeoutError("fake-secret"),
            UnrelatedTableExistsError("fake-secret"),
            RuntimeError("fake-secret"),
        ],
    )
    async def test_transient_errors_propagate_unchanged(self, error: Exception, finalize: bool) -> None:
        ctx = _ctx()
        client = FakeSnowflakeClient()
        writer = LocalSnowflakeWriter(ctx, client)

        with (
            mock.patch.object(client, "execute_async_query", side_effect=error),
            pytest.raises(type(error)) as caught,
        ):
            if finalize:
                await writer.finalize_run(ctx)
            else:
                await writer.write_batch(
                    _batches(_rows([1], ["a"])), DestinationBatchContext(run=ctx, batch_index=0, is_final_batch=False)
                )

        assert caught.value is error
        assert not isinstance(caught.value, DestinationConfigurationError)

    @pytest.mark.parametrize("missing", ["integration", "deleted_integration", "private_key", "password"])
    async def test_missing_connection_details_are_configuration_errors(self, missing: str) -> None:
        ctx = replace(_ctx(), integration_id=None if missing == "integration" else 42)
        writer = SnowflakeDestinationWriter(ctx)
        creds = mock.Mock(
            authentication_type="keypair" if missing == "private_key" else "password", private_key=None, password=None
        )

        with (
            mock.patch.object(
                snowflake,
                "get_snowflake_integration",
                return_value=creds,
                side_effect=SnowflakeIntegrationNotFoundError(42, 1) if missing == "deleted_integration" else None,
            ),
            pytest.raises(DestinationConfigurationError, match="connection details") as caught,
        ):
            await writer.write_batch(
                _batches(_rows([1], ["a"])), DestinationBatchContext(run=ctx, batch_index=0, is_final_batch=False)
            )

        assert caught.value.detail == MISSING_INTEGRATION_DETAIL
        assert str(caught.value).startswith(f"{ctx.destination_name}:")


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
