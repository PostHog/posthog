from typing import Any, cast

import pytest

import pyarrow as pa

from products.batch_exports.backend.facade.destinations.postgres import PostgreSQLClient
from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import DestinationRunContext
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.redshift import (
    RedshiftDestinationWriter,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.run_markers import (
    BATCH_INDEX_COLUMN,
)

pytestmark = pytest.mark.asyncio


class _FakeCursor:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.bound_rows: list[list[Any]] = []

    async def execute(self, query: Any, params: Any = None) -> None:
        self.statements.append(query.as_string(None) if hasattr(query, "as_string") else str(query))

    async def executemany(self, query: Any, params_seq: list[list[Any]]) -> None:
        self.bound_rows.extend(params_seq)


class _NullAsyncContext:
    async def __aenter__(self) -> "_NullAsyncContext":
        return self

    async def __aexit__(self, *exc_info: Any) -> bool:
        return False


class _FakeCursorContext:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    async def __aenter__(self) -> _FakeCursor:
        return self._cursor

    async def __aexit__(self, *exc_info: Any) -> bool:
        return False


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def transaction(self) -> _NullAsyncContext:
        return _NullAsyncContext()

    def cursor(self) -> _FakeCursorContext:
        return _FakeCursorContext(self._cursor)


class _FakeClient:
    """Stands in for `PostgreSQLClient`: just enough of its surface for
    `_drop_batch_index_column` to run against, with every statement it issues captured."""

    def __init__(self, columns: list[str]) -> None:
        self.cursor = _FakeCursor()
        self.connection = _FakeConnection(self.cursor)
        self._columns = columns

    async def aget_table_columns(self, schema: str, table: str) -> list[str]:
        return self._columns


def _ctx() -> DestinationRunContext:
    return DestinationRunContext(
        team_id=1,
        schema_id="schema",
        source_id="source",
        job_id="job",
        run_uuid="run",
        destination_id="destination",
        destination_type="Redshift",
        destination_name="test redshift",
        table_name="orders",
        sync_type="full_refresh",
        config={"schema": "public"},
    )


class TestDropBatchIndexColumn:
    """Unlike Postgres, Redshift's `ALTER TABLE ... DROP COLUMN` has no `IF EXISTS` clause and
    rejects the keyword with a syntax error, so a full refresh's `finalize_run` failed every
    time for a Redshift destination. The writer now checks the column is there itself first.
    """

    async def test_drops_the_column_without_if_exists_when_present(self) -> None:
        writer = RedshiftDestinationWriter(_ctx())
        client = _FakeClient(columns=["id", BATCH_INDEX_COLUMN])

        await writer._drop_batch_index_column(cast(PostgreSQLClient, client), "staging")

        statement = client.cursor.statements[-1]
        assert "DROP COLUMN" in statement
        assert "IF EXISTS" not in statement
        assert BATCH_INDEX_COLUMN in statement

    async def test_is_a_no_op_when_the_column_is_already_gone(self) -> None:
        # Exactly what a plain, unguarded `DROP COLUMN` (Redshift's only option, since it has
        # no `IF EXISTS`) would raise `UndefinedColumn` on: a staging table whose batch-index
        # column this method already dropped on an earlier, interrupted attempt.
        writer = RedshiftDestinationWriter(_ctx())
        client = _FakeClient(columns=["id"])

        await writer._drop_batch_index_column(cast(PostgreSQLClient, client), "staging")

        assert client.cursor.statements == []


class TestLoadBatchEgress:
    async def test_counts_the_encoded_size_of_every_bound_value(self) -> None:
        writer = RedshiftDestinationWriter(_ctx())
        client = _FakeClient(columns=[])
        batch = pa.RecordBatch.from_pylist(
            [
                {"id": 1, "name": "é", "tags": {"a": 1}},
                {"id": 22, "name": None, "tags": None},
            ]
        )

        bytes_sent = await writer._load_batch(cast(PostgreSQLClient, client), "orders", batch, ["id", "name", "tags"])

        assert client.cursor.bound_rows == [[1, "é", '{"a": 1}'], [22, None, None]]
        # "1" + "é" (2 bytes in UTF-8) + '{"a": 1}' + "22", and nothing for a NULL.
        assert bytes_sent == 1 + 2 + 8 + 2
