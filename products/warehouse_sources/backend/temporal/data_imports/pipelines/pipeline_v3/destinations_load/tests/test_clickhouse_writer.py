import json
import uuid
import decimal
import datetime as dt
from collections.abc import AsyncIterator, Iterator

import pytest
from unittest import mock

from django.conf import settings

import pyarrow as pa
from clickhouse_connect.driver.client import Client as ClickHouseClient

from posthog.hogql.escape_sql import backquote_clickhouse_identifier

from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import (
    DestinationBatchContext,
    DestinationRunContext,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.clickhouse import (
    SESSION_SETTINGS,
    ClickHouseDestinationWriter,
    IncompatibleTableError,
    UnrelatedTableExistsError,
    staging_table_name,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.run_markers import (
    published_marker,
    run_scope,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clickhouse.clickhouse import _get_client

TABLE = "charges"


def _connect() -> ClickHouseClient:
    return _get_client(
        host=settings.CLICKHOUSE_HOST,
        port=8123,
        database="",
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        secure=False,
        verify=False,
        settings=SESSION_SETTINGS,
    )


class LocalClickHouseWriter(ClickHouseDestinationWriter):
    async def _make_client(self) -> ClickHouseClient:
        return _connect()


@pytest.fixture
def database() -> Iterator[str]:
    name = f"ph_dest_test_{uuid.uuid4().hex[:10]}"
    yield name
    with _connect() as client:
        client.command(f"DROP DATABASE IF EXISTS `{name}`")


@pytest.fixture
def client() -> Iterator[ClickHouseClient]:
    with _connect() as client:
        yield client


def _ctx(
    database: str,
    sync_type: str,
    primary_keys: tuple[str, ...] = (),
    run_uuid: str = "run-a1",
    schema_id: str = "schema",
    table_name: str = TABLE,
) -> DestinationRunContext:
    return DestinationRunContext(
        team_id=1,
        schema_id=schema_id,
        source_id="source",
        job_id="job",
        run_uuid=run_uuid,
        destination_id="destination",
        destination_type="ClickHouse",
        destination_name="test clickhouse",
        table_name=table_name,
        sync_type=sync_type,
        primary_keys=primary_keys,
        config={"database": database},
    )


def _rows(ids: list[int], names: list[str]) -> pa.RecordBatch:
    return pa.RecordBatch.from_pydict({"id": pa.array(ids, pa.int64()), "name": names})


async def _batches(*record_batches: pa.RecordBatch) -> AsyncIterator[pa.RecordBatch]:
    for batch in record_batches:
        yield batch


async def _deliver(
    writer: ClickHouseDestinationWriter,
    run: DestinationRunContext,
    batch_index: int,
    batch: pa.RecordBatch,
    *,
    final: bool = False,
) -> None:
    await writer.write_batch(
        _batches(batch), DestinationBatchContext(run=run, batch_index=batch_index, is_final_batch=final)
    )
    if final:
        await writer.finalize_run(run)


def _read(client: ClickHouseClient, database: str, table: str = TABLE, *, final: bool = False) -> list[tuple]:
    modifier = " FINAL" if final else ""
    return [
        tuple(row)
        for row in client.query(f"SELECT id, name FROM `{database}`.`{table}`{modifier} ORDER BY id, name").result_rows
    ]


def _tables(client: ClickHouseClient, database: str) -> set[str]:
    return {
        row[0]
        for row in client.query(
            "SELECT name FROM system.tables WHERE database = {database:String}", parameters={"database": database}
        ).result_rows
    }


def _comment(client: ClickHouseClient, database: str, table: str) -> str:
    return client.query(
        "SELECT comment FROM system.tables WHERE database = {database:String} AND name = {table:String}",
        parameters={"database": database, "table": table},
    ).result_rows[0][0]


class TestFullRefresh:
    async def test_the_final_batch_publishes_every_batch(self, database: str, client: ClickHouseClient) -> None:
        run = _ctx(database, "full_refresh")
        writer = LocalClickHouseWriter(run)

        await _deliver(writer, run, 0, _rows([1, 2], ["a", "b"]))
        await _deliver(writer, run, 1, _rows([3], ["c"]), final=True)

        assert _read(client, database) == [(1, "a"), (2, "b"), (3, "c")]
        assert _tables(client, database) == {TABLE}
        assert _comment(client, database, TABLE) == published_marker("schema", run.run_uuid)

    async def test_a_second_run_replaces_the_first(self, database: str, client: ClickHouseClient) -> None:
        first = _ctx(database, "full_refresh", run_uuid="run-a1")
        await _deliver(LocalClickHouseWriter(first), first, 0, _rows([1, 2], ["a", "b"]), final=True)

        second = _ctx(database, "full_refresh", run_uuid="run-b1")
        await _deliver(LocalClickHouseWriter(second), second, 0, _rows([3], ["c"]), final=True)

        assert _read(client, database) == [(3, "c")]
        assert _tables(client, database) == {TABLE}

    async def test_a_redelivered_final_batch_leaves_the_published_table_alone(
        self, database: str, client: ClickHouseClient
    ) -> None:
        run = _ctx(database, "full_refresh")
        writer = LocalClickHouseWriter(run)
        await _deliver(writer, run, 0, _rows([1, 2], ["a", "b"]))
        await _deliver(writer, run, 1, _rows([3], ["c"]), final=True)

        await _deliver(writer, run, 1, _rows([3], ["c"]), final=True)

        assert _read(client, database) == [(1, "a"), (2, "b"), (3, "c")]
        assert _tables(client, database) == {TABLE}

    async def test_a_run_that_stopped_after_the_exchange_publishes_on_replay(
        self, database: str, client: ClickHouseClient
    ) -> None:
        first = _ctx(database, "full_refresh", run_uuid="run-a1")
        await _deliver(LocalClickHouseWriter(first), first, 0, _rows([1, 2], ["a", "b"]), final=True)

        second = _ctx(database, "full_refresh", run_uuid="run-b1")
        writer = LocalClickHouseWriter(second)
        await writer.write_batch(
            _batches(_rows([3], ["c"])), DestinationBatchContext(run=second, batch_index=0, is_final_batch=True)
        )
        with mock.patch.object(ClickHouseDestinationWriter, "_drop_if_owned", side_effect=RuntimeError("pod killed")):
            with pytest.raises(RuntimeError, match="pod killed"):
                await writer.finalize_run(second)

        await _deliver(writer, second, 0, _rows([3], ["c"]), final=True)

        assert _read(client, database) == [(3, "c")]
        assert _tables(client, database) == {TABLE}

    async def test_abort_drops_the_staging_table(self, database: str, client: ClickHouseClient) -> None:
        run = _ctx(database, "full_refresh")
        writer = LocalClickHouseWriter(run)
        await _deliver(writer, run, 0, _rows([1], ["a"]))
        assert staging_table_name(run) in _tables(client, database)

        await writer.abort_run(run)
        await writer.abort_run(run)

        assert _tables(client, database) == set()

    def test_a_long_table_name_keeps_its_run_suffix(self) -> None:
        run = _ctx("default", "full_refresh", run_uuid=str(uuid.uuid4()), table_name="é" * 150)

        name = staging_table_name(run)

        assert name.endswith(f"__ph_stage_{run_scope(run.run_uuid)}")
        assert len(name.encode()) <= 200


class TestRedelivery:
    @pytest.mark.parametrize("sync_type", ["full_refresh", "incremental"])
    async def test_a_redelivered_batch_lands_once_and_an_identical_next_batch_still_lands(
        self, sync_type: str, database: str, client: ClickHouseClient
    ) -> None:
        run = _ctx(database, sync_type)
        writer = LocalClickHouseWriter(run)
        batch = _rows([1, 2], ["a", "b"])

        await _deliver(writer, run, 0, batch)
        await _deliver(writer, run, 0, batch)
        await _deliver(writer, run, 1, batch, final=True)

        assert _read(client, database) == [(1, "a"), (1, "a"), (2, "b"), (2, "b")]


class TestIncremental:
    async def test_a_later_batch_replaces_rows_by_key(self, database: str, client: ClickHouseClient) -> None:
        run = _ctx(database, "incremental", primary_keys=("id",))
        writer = LocalClickHouseWriter(run)

        await _deliver(writer, run, 0, _rows([1, 2], ["a", "b"]))
        await _deliver(writer, run, 1, _rows([2, 3, 2], ["b2", "c", "b3"]))

        assert _read(client, database, final=True) == [(1, "a"), (2, "b3"), (3, "c")]

    async def test_a_retried_attempt_replaces_what_an_earlier_attempt_wrote(
        self, database: str, client: ClickHouseClient
    ) -> None:
        first_attempt = _ctx(database, "incremental", primary_keys=("id",), run_uuid="run-a1")
        writer = LocalClickHouseWriter(first_attempt)
        await _deliver(writer, first_attempt, 0, _rows([1], ["first"]))
        await _deliver(writer, first_attempt, 1, _rows([1], ["stale"]))

        second_attempt = _ctx(database, "incremental", primary_keys=("id",), run_uuid="run-a2")
        await _deliver(LocalClickHouseWriter(second_attempt), second_attempt, 0, _rows([1], ["fresh"]))

        assert _read(client, database, final=True) == [(1, "fresh")]

    async def test_a_column_the_source_grows_is_added(self, database: str, client: ClickHouseClient) -> None:
        run = _ctx(database, "incremental")
        writer = LocalClickHouseWriter(run)

        await _deliver(writer, run, 0, _rows([1], ["a"]))
        await _deliver(
            writer,
            run,
            1,
            pa.RecordBatch.from_pydict({"id": pa.array([2], pa.int64()), "name": ["b"], "email": ["b@example.com"]}),
        )

        rows = client.query(f"SELECT id, name, email FROM `{database}`.`{TABLE}` ORDER BY id").result_rows
        assert [tuple(row) for row in rows] == [(1, "a", None), (2, "b", "b@example.com")]


class TestTableOwnership:
    def _create_unrelated_table(self, client: ClickHouseClient, database: str) -> None:
        client.command(f"CREATE DATABASE IF NOT EXISTS `{database}`")
        client.command(
            f"CREATE TABLE `{database}`.`{TABLE}` (`id` Int64, `name` String) ENGINE = MergeTree ORDER BY id"
        )
        client.command(f"INSERT INTO `{database}`.`{TABLE}` VALUES (1, 'theirs')")

    async def test_refuses_to_write_into_a_table_it_did_not_create(
        self, database: str, client: ClickHouseClient
    ) -> None:
        self._create_unrelated_table(client, database)
        run = _ctx(database, "incremental", primary_keys=("id",))

        with pytest.raises(UnrelatedTableExistsError):
            await _deliver(LocalClickHouseWriter(run), run, 0, _rows([2], ["ours"]))

        assert _read(client, database) == [(1, "theirs")]

    async def test_refuses_to_replace_a_table_it_did_not_create(self, database: str, client: ClickHouseClient) -> None:
        self._create_unrelated_table(client, database)
        run = _ctx(database, "full_refresh")

        with pytest.raises(UnrelatedTableExistsError):
            await _deliver(LocalClickHouseWriter(run), run, 0, _rows([2], ["ours"]), final=True)

        assert _read(client, database) == [(1, "theirs")]

    async def test_refuses_a_table_keyed_on_other_columns(self, database: str, client: ClickHouseClient) -> None:
        unkeyed = _ctx(database, "incremental")
        await _deliver(LocalClickHouseWriter(unkeyed), unkeyed, 0, _rows([1], ["a"]))

        keyed = _ctx(database, "incremental", primary_keys=("id",))
        with pytest.raises(IncompatibleTableError):
            await _deliver(LocalClickHouseWriter(keyed), keyed, 0, _rows([1], ["b"]))


class TestValueFidelity:
    async def test_values_land_as_the_source_sent_them(self, database: str, client: ClickHouseClient) -> None:
        batch = pa.RecordBatch.from_pydict(
            {
                "id": pa.array([1], pa.int64()),
                "day": pa.array([dt.date(2024, 1, 2)], pa.date32()),
                "valid_until": pa.array([dt.date(9999, 12, 31)], pa.date32()),
                "amount": pa.array([decimal.Decimal("12.3400")], pa.decimal128(18, 4)),
                "paid_at": pa.array([dt.datetime(2024, 1, 2, 3, 4, 5, 6)], pa.timestamp("us", tz="UTC")),
                "local_at": pa.array([dt.datetime(2024, 1, 2, 3, 4, 5, 6)], pa.timestamp("us")),
                "opens_at": pa.array([dt.time(9, 30)], pa.time64("us")),
                "metadata": pa.array([{"plan": "pro", "seats": 3}]),
                "tags": pa.array([["a", "b"]]),
                "refunded": pa.array([False]),
                "raw": pa.array([b"\x00\xff"], pa.binary()),
                "status": pa.array(["active"]).dictionary_encode(),
                "always_empty": pa.array([None], pa.null()),
            }
        )
        run = _ctx(database, "incremental")

        await _deliver(LocalClickHouseWriter(run), run, 0, batch)

        row = client.query(
            "SELECT toString(day), toString(valid_until), toString(amount), toString(paid_at), toString(local_at), "
            "opens_at, metadata, tags, refunded, hex(raw), status, always_empty "
            f"FROM `{database}`.`{TABLE}`"
        ).result_rows[0]
        assert tuple(row[:6]) == (
            "2024-01-02",
            "2299-12-31",
            "12.34",
            "2024-01-02 03:04:05.000006",
            "2024-01-02 03:04:05.000006",
            "09:30:00.000000",
        )
        assert json.loads(row[6]) == {"plan": "pro", "seats": 3}
        assert json.loads(row[7]) == ["a", "b"]
        assert tuple(row[8:]) == (False, "00FF", "active", None)


class TestIdentifierQuoting:
    async def test_names_that_need_quoting_land_as_given(self, database: str, client: ClickHouseClient) -> None:
        columns = ["id", "has space", "`quoted`", "back\\slash"]
        batch = pa.RecordBatch.from_pydict(
            {"id": pa.array([1], pa.int64()), "has space": ["a"], "`quoted`": ["b"], "back\\slash": ["c"]}
        )
        table = "we`ird\\table"
        run = _ctx(database, "incremental", table_name=table)

        await _deliver(LocalClickHouseWriter(run), run, 0, batch)

        stored = client.query(
            "SELECT name FROM system.columns WHERE database = {database:String} AND table = {table:String} "
            "ORDER BY position",
            parameters={"database": database, "table": table},
        ).result_rows
        assert [row[0] for row in stored] == columns
        values = client.query(f"SELECT * FROM `{database}`.{backquote_clickhouse_identifier(table)}").result_rows
        assert [tuple(row) for row in values] == [(1, "a", "b", "c")]
