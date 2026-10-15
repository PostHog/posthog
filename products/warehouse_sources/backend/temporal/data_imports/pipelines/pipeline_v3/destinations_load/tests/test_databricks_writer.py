from collections.abc import AsyncIterator
from dataclasses import replace

import pytest
from unittest import mock

import pyarrow as pa
from databricks.sql.exc import ServerOperationError
from parameterized import parameterized

from products.batch_exports.backend.facade.destinations.databricks import (
    DatabricksCatalogNotFoundError,
    DatabricksClient,
    DatabricksConnectionError,
    DatabricksIncompatibleSchemaError,
    DatabricksInsufficientPermissionsError,
    DatabricksIntegrationNotFoundError,
    DatabricksOperationTimeoutError,
    DatabricksSchemaNotFoundError,
    DatabricksWarehouseStoppedError,
)
from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import (
    DestinationBatchContext,
    DestinationRunContext,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.errors import (
    MISSING_INTEGRATION_DETAIL,
    DestinationConfigurationError,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.tests.fake_databricks import (
    FakeDatabricksClient,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers import (
    databricks,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.databricks import (
    DatabricksDestinationWriter,
    UnrelatedTableExistsError,
)

pytestmark = pytest.mark.asyncio


class LocalDatabricksWriter(DatabricksDestinationWriter):
    """Points the writer at an in-memory Databricks instead of a customer's workspace."""

    def __init__(self, ctx: DestinationRunContext, client: FakeDatabricksClient) -> None:
        super().__init__(ctx)
        self._fake = client

    async def _make_client(self) -> DatabricksClient:
        return self._fake  # type: ignore[return-value]  # ty: ignore[invalid-return-type]


async def _batches(*record_batches: pa.RecordBatch) -> AsyncIterator[pa.RecordBatch]:
    for batch in record_batches:
        yield batch


def _rows(ids: list[int], names: list[str]) -> pa.RecordBatch:
    return pa.RecordBatch.from_pydict({"id": ids, "name": names})


def _ctx(table_name: str, run_uuid: str, schema_id: str = "schema") -> DestinationRunContext:
    return DestinationRunContext(
        team_id=1,
        schema_id=schema_id,
        source_id="source",
        job_id="job",
        run_uuid=run_uuid,
        destination_id="destination",
        destination_type="Databricks",
        destination_name="test databricks",
        table_name=table_name,
        sync_type="incremental",
        config={"catalog": "main", "schema": "Default", "http_path": "/sql/1.0", "volume": "vol"},
    )


def _read(client: FakeDatabricksClient, table: str) -> list[tuple]:
    return sorted((row["id"], row["name"]) for row in client.tables[table.lower()].rows)


class TestConfigurationErrors:
    @pytest.mark.parametrize("finalize", [False, True], ids=["write_batch", "finalize_run"])
    @pytest.mark.parametrize(
        ("error", "detail_word"),
        [
            (DatabricksConnectionError("fake-secret", retryable=False), "hostname"),
            (DatabricksInsufficientPermissionsError("CREATE TABLE", "fake-secret"), "WRITE VOLUME"),
            (DatabricksCatalogNotFoundError("fake-secret"), "catalog"),
            (DatabricksSchemaNotFoundError("fake-secret"), "schema"),
            (DatabricksIntegrationNotFoundError("fake-secret"), "connection details"),
        ],
    )
    async def test_permanent_errors_are_configuration_errors(
        self, error: Exception, detail_word: str, finalize: bool
    ) -> None:
        ctx = replace(_ctx("charges", "run-a1"), sync_type="full_refresh")
        client = FakeDatabricksClient()
        writer = LocalDatabricksWriter(ctx, client)
        target = client if isinstance(error, DatabricksInsufficientPermissionsError) else writer
        method = "aget_table_columns" if isinstance(error, DatabricksInsufficientPermissionsError) else "_make_client"

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
            DatabricksConnectionError("fake-secret", retryable=True),
            DatabricksConnectionError("fake-secret"),
            DatabricksOperationTimeoutError("COPY INTO", 1),
            DatabricksWarehouseStoppedError("COPY INTO", "fake-secret"),
            DatabricksIncompatibleSchemaError("COPY INTO", "fake-secret"),
            ServerOperationError("fake-secret"),
            TimeoutError("fake-secret"),
            UnrelatedTableExistsError("fake-secret"),
            OSError("fake-secret"),
        ],
    )
    async def test_transient_errors_propagate_unchanged(self, error: Exception, finalize: bool) -> None:
        ctx = replace(_ctx("charges", "run-a1"), sync_type="full_refresh")
        client = FakeDatabricksClient()
        writer = LocalDatabricksWriter(ctx, client)

        with (
            mock.patch.object(client, "aget_table_columns", side_effect=error),
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

    @pytest.mark.parametrize("integration_id", [None, 42])
    async def test_missing_connection_details_are_configuration_errors(self, integration_id: int | None) -> None:
        ctx = replace(_ctx("charges", "run-a1"), integration_id=integration_id)
        writer = DatabricksDestinationWriter(ctx)

        with (
            mock.patch.object(
                databricks, "_load_integration", side_effect=DatabricksIntegrationNotFoundError("fake-secret")
            ),
            pytest.raises(DestinationConfigurationError, match="connection details") as caught,
        ):
            await writer.write_batch(
                _batches(_rows([1], ["a"])), DestinationBatchContext(run=ctx, batch_index=0, is_final_batch=False)
            )

        assert caught.value.detail == MISSING_INTEGRATION_DETAIL
        assert str(caught.value).startswith(f"{ctx.destination_name}:")
        assert "fake-secret" not in caught.value.detail


class TestUnityCatalogNameCase:
    """Unity Catalog lowercases the names it stores, so a writer that looks its own table up
    case-sensitively stops recognizing it as soon as the name carries any uppercase. The run
    that created the table then reports it as somebody else's, on this run and on every later
    one, because nothing about the name changes.
    """

    @parameterized.expand(
        [
            ("all lowercase", "charges"),
            ("mixed case", "Stripe_Charges"),
            ("all uppercase", "CHARGES"),
        ]
    )
    async def test_a_later_run_writes_into_the_table_an_earlier_run_created(self, _name: str, table_name: str) -> None:
        client = FakeDatabricksClient()
        first = _ctx(table_name, "run-a1")
        second = _ctx(table_name, "run-b2")

        await LocalDatabricksWriter(first, client).write_batch(
            _batches(_rows([1], ["a"])),
            DestinationBatchContext(run=first, batch_index=0, is_final_batch=True),
        )
        await LocalDatabricksWriter(second, client).write_batch(
            _batches(_rows([2], ["b"])),
            DestinationBatchContext(run=second, batch_index=0, is_final_batch=True),
        )

        assert _read(client, table_name) == [(1, "a"), (2, "b")]

    async def test_a_table_a_different_schema_created_is_still_refused(self) -> None:
        # The case-insensitive lookup must not turn into "any table is ours": ownership is
        # scoped to the schema whose sync created the table.
        client = FakeDatabricksClient()
        first = _ctx("Charges", "run-a1", schema_id="schema-a")
        second = _ctx("Charges", "run-b2", schema_id="schema-b")

        await LocalDatabricksWriter(first, client).write_batch(
            _batches(_rows([1], ["a"])),
            DestinationBatchContext(run=first, batch_index=0, is_final_batch=True),
        )

        with pytest.raises(UnrelatedTableExistsError):
            await LocalDatabricksWriter(second, client).write_batch(
                _batches(_rows([2], ["b"])),
                DestinationBatchContext(run=second, batch_index=0, is_final_batch=True),
            )

        assert _read(client, "Charges") == [(1, "a")]
