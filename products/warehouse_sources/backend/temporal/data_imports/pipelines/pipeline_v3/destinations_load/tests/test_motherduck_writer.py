from __future__ import annotations

import decimal
import datetime as dt
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from unittest import mock

import duckdb
import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import (
    DestinationBatchContext,
    DestinationRunContext,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.errors import (
    DestinationConfigurationError,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.motherduck import (
    AUTHENTICATION_FAILED_DETAIL,
    COMPUTE_LIMIT_DETAIL,
    INVALID_DATABASE_DETAIL,
    READ_ONLY_DETAIL,
    RECEIPTS_TABLE,
    UNKNOWN_DATABASE_DETAIL,
    MotherDuckDestinationWriter,
    UnrelatedTableExistsError,
    configuration_error_detail,
    duckdb_compatible_batch,
    staging_table_name,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.run_markers import (
    BATCH_INDEX_COLUMN,
    owned_marker,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.motherduck.motherduck import (
    MotherDuckConnectionError,
)

SCHEMA = "analytics"


def _ctx(
    sync_type: str = "full_refresh",
    *,
    run_uuid: str = "run-a1",
    schema_id: str = "schema-1",
    table_name: str = "charges",
    primary_keys: tuple[str, ...] = ("id",),
    config: dict[str, Any] | None = None,
    integration_id: int | None = 42,
) -> DestinationRunContext:
    return DestinationRunContext(
        team_id=1,
        schema_id=schema_id,
        source_id="source",
        job_id="job",
        run_uuid=run_uuid,
        destination_id="destination",
        destination_type="MotherDuck",
        destination_name="test motherduck",
        table_name=table_name,
        sync_type=sync_type,
        primary_keys=primary_keys,
        config={"database": "analytics_db", "schema": SCHEMA} if config is None else config,
        integration_id=integration_id,
    )


async def _stream(*batches: pa.RecordBatch) -> AsyncIterator[pa.RecordBatch]:
    for batch in batches:
        yield batch


def _batch(**columns: list[Any]) -> pa.RecordBatch:
    return pa.RecordBatch.from_pydict(columns)


class LocalDuckDB:
    """A destination backed by a DuckDB file, which runs the same SQL MotherDuck does."""

    def __init__(self, path: Path) -> None:
        self.path = str(path)

    def connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(self.path)

    def writer(self, ctx: DestinationRunContext) -> MotherDuckDestinationWriter:
        return MotherDuckDestinationWriter(ctx, connector=self.connect)

    async def write(self, ctx: DestinationRunContext, batch_index: int, *batches: pa.RecordBatch) -> int:
        outcome = await self.writer(ctx).write_batch(
            _stream(*batches), DestinationBatchContext(run=ctx, batch_index=batch_index, is_final_batch=False)
        )
        return outcome.rows_written

    async def sync(self, ctx: DestinationRunContext, *batches: pa.RecordBatch) -> None:
        for index, batch in enumerate(batches):
            await self.write(ctx, index, batch)
        await self.writer(ctx).finalize_run(ctx)

    def rows(self, table: str, order_by: str = "id") -> list[tuple]:
        with self.connect() as connection:
            return connection.execute(f'SELECT * FROM "{SCHEMA}"."{table}" ORDER BY "{order_by}"').fetchall()

    def columns(self, table: str) -> dict[str, str]:
        with self.connect() as connection:
            return {
                row[0]: row[1]
                for row in connection.execute(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = ? AND table_name = ?",
                    [SCHEMA, table],
                ).fetchall()
            }

    def tables(self) -> set[str]:
        with self.connect() as connection:
            return {row[0] for row in connection.execute("SELECT table_name FROM duckdb_tables()").fetchall()}

    def execute(self, statement: str) -> None:
        with self.connect() as connection:
            connection.execute(statement)


@pytest.fixture
def destination(tmp_path: Path) -> LocalDuckDB:
    return LocalDuckDB(tmp_path / "analytics_db.duckdb")


class TestFullRefresh:
    async def test_the_live_table_only_changes_once_the_run_completes(self, destination: LocalDuckDB) -> None:
        await destination.sync(_ctx(run_uuid="run-1"), _batch(id=[1], name=["old"]))

        second = _ctx(run_uuid="run-2")
        await destination.write(second, 0, _batch(id=[2], name=["new"]))
        assert destination.rows("charges") == [(1, "old")]

        await destination.writer(second).finalize_run(second)
        assert destination.rows("charges") == [(2, "new")]
        assert staging_table_name(second) not in destination.tables()

    async def test_reapplying_a_batch_does_not_duplicate_its_rows(self, destination: LocalDuckDB) -> None:
        ctx = _ctx()
        await destination.write(ctx, 0, _batch(id=[1, 2]))
        await destination.write(ctx, 1, _batch(id=[3]))
        await destination.write(ctx, 1, _batch(id=[3]))
        await destination.writer(ctx).finalize_run(ctx)

        assert destination.rows("charges") == [(1,), (2,), (3,)]

    async def test_a_batch_of_several_record_batches_is_cleared_once_before_reapply(
        self, destination: LocalDuckDB
    ) -> None:
        ctx = _ctx()
        for _ in range(2):
            written = await destination.write(ctx, 0, _batch(id=[1]), _batch(id=[2]))
        await destination.writer(ctx).finalize_run(ctx)

        assert written == 2
        assert destination.rows("charges") == [(1,), (2,)]

    async def test_replaying_the_published_final_batch_keeps_the_earlier_batches(
        self, destination: LocalDuckDB
    ) -> None:
        ctx = _ctx()
        await destination.sync(ctx, _batch(id=[1]), _batch(id=[2]))

        assert await destination.write(ctx, 1, _batch(id=[2])) == 0
        await destination.writer(ctx).finalize_run(ctx)

        assert destination.rows("charges") == [(1,), (2,)]

    async def test_the_published_table_does_not_carry_the_batch_index_column(self, destination: LocalDuckDB) -> None:
        await destination.sync(_ctx(), _batch(id=[1]))

        assert BATCH_INDEX_COLUMN not in destination.columns("charges")

    @pytest.mark.parametrize("existing_name", ["charges", "Charges"])
    @pytest.mark.parametrize("schema", [SCHEMA, SCHEMA.upper()])
    async def test_refuses_to_replace_a_table_it_did_not_create(
        self, destination: LocalDuckDB, existing_name: str, schema: str
    ) -> None:
        destination.execute(f'CREATE SCHEMA "{SCHEMA}"')
        destination.execute(f'CREATE TABLE "{SCHEMA}"."{existing_name}" AS SELECT 99 AS id')
        ctx = _ctx(config={"database": "analytics_db", "schema": schema})
        await destination.write(ctx, 0, _batch(id=[1]))

        with pytest.raises(UnrelatedTableExistsError):
            await destination.writer(ctx).finalize_run(ctx)
        assert destination.rows("charges") == [(99,)]

    async def test_refuses_to_replace_a_table_another_schema_created(self, destination: LocalDuckDB) -> None:
        await destination.sync(_ctx(schema_id="other-schema"), _batch(id=[99]))
        ctx = _ctx(run_uuid="run-2")
        await destination.write(ctx, 0, _batch(id=[1]))

        with pytest.raises(UnrelatedTableExistsError):
            await destination.writer(ctx).finalize_run(ctx)

    async def test_abort_drops_the_staging_table(self, destination: LocalDuckDB) -> None:
        ctx = _ctx()
        await destination.write(ctx, 0, _batch(id=[1]))
        await destination.writer(ctx).abort_run(ctx)

        assert staging_table_name(ctx) not in destination.tables()

    async def test_abort_keeps_a_table_under_the_staging_name_it_did_not_create(self, destination: LocalDuckDB) -> None:
        ctx = _ctx()
        destination.execute(f'CREATE SCHEMA "{SCHEMA}"')
        destination.execute(f'CREATE TABLE "{SCHEMA}"."{staging_table_name(ctx)}" AS SELECT 99 AS id')

        with pytest.raises(UnrelatedTableExistsError):
            await destination.write(ctx, 0, _batch(id=[1]))
        await destination.writer(ctx).abort_run(ctx)

        assert destination.rows(staging_table_name(ctx)) == [(99,)]

    async def test_a_long_table_name_keeps_its_run_suffix(self, destination: LocalDuckDB) -> None:
        ctx = _ctx(table_name="t" * 300)

        assert staging_table_name(ctx).endswith("__ph_stage_runa1")
        await destination.sync(ctx, _batch(id=[1]))
        assert destination.rows("t" * 300) == [(1,)]


class TestIncremental:
    async def test_merges_on_the_primary_key_keeping_the_last_duplicate(self, destination: LocalDuckDB) -> None:
        ctx = _ctx("incremental")
        await destination.write(ctx, 0, _batch(id=[1, 2], name=["a", "b"]))
        await destination.write(ctx, 1, _batch(id=[2, 3, 3], name=["b1", "c1", "c2"]))

        assert destination.rows("charges") == [(1, "a"), (2, "b1"), (3, "c2")]

    async def test_merges_into_a_table_with_columns_the_batch_lacks(self, destination: LocalDuckDB) -> None:
        ctx = _ctx("incremental")
        await destination.write(ctx, 0, _batch(id=[1], name=["a"], note=["kept"]))
        await destination.write(ctx, 1, _batch(id=[1], name=["b"]))

        assert destination.rows("charges") == [(1, "b", "kept")]

    async def test_a_later_batch_adds_new_columns(self, destination: LocalDuckDB) -> None:
        ctx = _ctx("incremental")
        await destination.write(ctx, 0, _batch(id=[1]))
        await destination.write(ctx, 1, _batch(id=[2], amount=[5.5]))

        assert destination.rows("charges") == [(1, None), (2, 5.5)]

    @pytest.mark.parametrize("existing_name", ["charges", "CHARGES"])
    @pytest.mark.parametrize("schema", [SCHEMA, SCHEMA.upper()])
    async def test_refuses_to_merge_into_a_table_it_did_not_create(
        self, destination: LocalDuckDB, existing_name: str, schema: str
    ) -> None:
        destination.execute(f'CREATE SCHEMA "{SCHEMA}"')
        destination.execute(f'CREATE TABLE "{SCHEMA}"."{existing_name}" AS SELECT 99 AS id')
        ctx = _ctx("incremental", config={"database": "analytics_db", "schema": schema})

        with pytest.raises(UnrelatedTableExistsError):
            await destination.write(ctx, 0, _batch(id=[1]))
        assert destination.rows("charges") == [(99,)]

    async def test_merges_into_a_table_it_marked_as_its_own(self, destination: LocalDuckDB) -> None:
        destination.execute(f'CREATE SCHEMA "{SCHEMA}"')
        destination.execute(f'CREATE TABLE "{SCHEMA}"."charges" AS SELECT 1::BIGINT AS id, \'a\' AS name')
        destination.execute(f'COMMENT ON TABLE "{SCHEMA}"."charges" IS \'{owned_marker("schema-1")}\'')

        await destination.write(_ctx("incremental"), 0, _batch(id=[1], name=["b"]))

        assert destination.rows("charges") == [(1, "b")]

    @pytest.mark.parametrize("sync_type", ["append", "incremental"])
    async def test_appends_when_no_merge_applies(self, destination: LocalDuckDB, sync_type: str) -> None:
        primary_keys = ("id",) if sync_type == "append" else ()
        ctx = _ctx(sync_type, primary_keys=primary_keys)
        await destination.write(ctx, 0, _batch(id=[1]))
        await destination.write(ctx, 1, _batch(id=[1]))

        assert destination.rows("charges") == [(1,), (1,)]

    @pytest.mark.parametrize(
        ("first_attempt", "redelivery"),
        [
            ([[1, 2]], [[1, 2]]),
            ([[1]], [[1], [2]]),
        ],
        ids=["whole_batch_again", "after_a_crash_mid_batch"],
    )
    async def test_a_redelivered_append_batch_is_not_inserted_twice(
        self, destination: LocalDuckDB, first_attempt: list[list[int]], redelivery: list[list[int]]
    ) -> None:
        ctx = _ctx("append")
        await destination.write(ctx, 0, *[_batch(id=ids) for ids in first_attempt])
        await destination.write(ctx, 0, *[_batch(id=ids) for ids in redelivery])

        assert destination.rows("charges") == [(1,), (2,)]

    async def test_a_later_append_run_keeps_only_its_own_receipts(self, destination: LocalDuckDB) -> None:
        first, second = _ctx("append", run_uuid="run-1"), _ctx("append", run_uuid="run-2")
        await destination.sync(first, _batch(id=[1]))
        await destination.sync(second, _batch(id=[2]))

        assert destination.rows("charges") == [(1,), (2,)]
        assert destination.rows(RECEIPTS_TABLE, order_by="run_uuid") == [("schema-1", "run-2", 0, 0)]

    async def test_a_batch_missing_a_primary_key_column_is_not_merged(self, destination: LocalDuckDB) -> None:
        ctx = _ctx("incremental", primary_keys=("id", "region"))
        await destination.write(ctx, 0, _batch(id=[1], region=["eu"], name=["a"]))

        with pytest.raises(ValueError, match="region"):
            await destination.write(ctx, 1, _batch(id=[1], name=["b"]))
        assert destination.rows("charges") == [(1, "eu", "a")]


class TestTypes:
    async def test_stores_types_duckdb_has_no_direct_mapping_for(self, destination: LocalDuckDB) -> None:
        ctx = _ctx("incremental")
        first = pa.RecordBatch.from_pydict(
            {
                "id": pa.array([1], pa.int64()),
                "empty": pa.array([None], pa.null()),
                "small_decimal": pa.array([decimal.Decimal("1.50")], pa.decimal256(10, 2)),
                "huge_decimal": pa.array([decimal.Decimal("1" * 45)], pa.decimal256(50, 0)),
                "nested": pa.array([{"amount": decimal.Decimal("2.5")}], pa.struct([("amount", pa.decimal256(5, 1))])),
                "tags": pa.array([["a"]], pa.list_(pa.string())),
                "at": pa.array([dt.datetime(2024, 1, 1)], pa.timestamp("us", tz="UTC")),
            }
        )
        await destination.write(ctx, 0, first)
        await destination.write(ctx, 1, _batch(id=[2], empty=["now text"]))

        columns = destination.columns("charges")
        assert columns["empty"] == "VARCHAR"
        assert columns["small_decimal"] == "DECIMAL(10,2)"
        assert columns["huge_decimal"] == "VARCHAR"
        assert columns["nested"] == "STRUCT(amount DECIMAL(5,1))"
        assert columns["at"] == "TIMESTAMP WITH TIME ZONE"
        rows = destination.rows("charges")
        assert rows[0][3] == "1" * 45
        assert rows[1][1] == "now text"

    @pytest.mark.parametrize(
        "arrow_type",
        [pa.int64(), pa.string(), pa.decimal128(10, 2), pa.struct([("a", pa.int64())])],
        ids=["int", "string", "decimal128", "struct"],
    )
    def test_leaves_supported_types_untouched(self, arrow_type: pa.DataType) -> None:
        batch = pa.RecordBatch.from_arrays([pa.array([None], arrow_type)], names=["value"])

        assert duckdb_compatible_batch(batch) is batch


class TestConfigurationErrors:
    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            ("Invalid Input Error: Unauthenticated: invalid token", AUTHENTICATION_FAILED_DETAIL),
            ("Invalid Input Error: Failed to authenticate", AUTHENTICATION_FAILED_DETAIL),
            ('Catalog Error: database "missing" does not exist', UNKNOWN_DATABASE_DETAIL),
            ("Invalid Input Error: no database/share named 'missing' found", UNKNOWN_DATABASE_DETAIL),
            ("Invalid Input Error: Cannot execute statement of type CREATE on read-only database", READ_ONLY_DETAIL),
            ("Invalid Input Error: account is out of compute", COMPUTE_LIMIT_DETAIL),
            ("Invalid Input Error: Could not connect to MotherDuck. Please try again later.", None),
            ("Invalid Error: Encountered an internal MotherDuck error (id: abc)", None),
            ("TransactionContext Error: Catalog write-write conflict on alter with table", None),
            ("IO Error: Connection reset by peer", None),
        ],
    )
    def test_classifies_driver_messages(self, message: str, expected: str | None) -> None:
        assert configuration_error_detail(duckdb.Error(message)) == expected

    def test_reads_the_driver_error_behind_the_source_connection_error(self) -> None:
        wrapped = MotherDuckConnectionError("MotherDuck is temporarily unavailable.")
        wrapped.__cause__ = duckdb.Error("Could not connect to MotherDuck. Please try again later.")

        assert configuration_error_detail(wrapped) is None

    @pytest.mark.parametrize(
        ("error", "is_configuration_error"),
        [
            (duckdb.Error("Unauthenticated: invalid token"), True),
            (duckdb.TransactionException("write-write conflict"), False),
            (duckdb.IOException("Connection reset by peer"), False),
        ],
    )
    @pytest.mark.parametrize("at_connect", [True, False], ids=["connect", "statement"])
    async def test_a_permanent_error_fails_the_run_and_others_propagate(
        self, destination: LocalDuckDB, error: Exception, is_configuration_error: bool, at_connect: bool
    ) -> None:
        def failing_connect() -> duckdb.DuckDBPyConnection:
            if at_connect:
                raise error
            connection = mock.MagicMock(wraps=destination.connect())
            connection.execute.side_effect = error
            return connection

        writer = MotherDuckDestinationWriter(_ctx(), connector=failing_connect)
        batch_ctx = DestinationBatchContext(run=_ctx(), batch_index=0, is_final_batch=False)

        expected = DestinationConfigurationError if is_configuration_error else type(error)
        with pytest.raises(expected):
            await writer.write_batch(_stream(_batch(id=[1])), batch_ctx)

    @pytest.mark.parametrize("database", ["", "  ", "bad name?motherduck_token=x"], ids=["empty", "blank", "unsafe"])
    async def test_a_missing_or_unsafe_database_is_a_configuration_error(self, database: str) -> None:
        ctx = _ctx(config={"database": database})
        writer = MotherDuckDestinationWriter(ctx)

        with mock.patch.object(writer, "_access_token", mock.AsyncMock(return_value="token")):
            with pytest.raises(DestinationConfigurationError) as raised:
                await writer.finalize_run(ctx)
        assert raised.value.detail == INVALID_DATABASE_DETAIL

    async def test_a_stalled_statement_is_interrupted_and_the_batch_fails(self, destination: LocalDuckDB) -> None:
        real = destination.connect()
        stalled = mock.MagicMock(wraps=real)
        stalled.execute.side_effect = lambda *_args, **_kwargs: real.execute(
            "SELECT sum(i) FROM range(1000000000000) t(i)"
        )
        writer = MotherDuckDestinationWriter(_ctx(), connector=lambda: stalled, operation_timeout_seconds=0.2)

        with pytest.raises(TimeoutError):
            await writer.write_batch(
                _stream(_batch(id=[1])), DestinationBatchContext(run=_ctx(), batch_index=0, is_final_batch=False)
            )

    async def test_a_destination_without_an_integration_is_a_configuration_error(self) -> None:
        ctx = _ctx(integration_id=None)

        with pytest.raises(DestinationConfigurationError):
            await MotherDuckDestinationWriter(ctx).finalize_run(ctx)
