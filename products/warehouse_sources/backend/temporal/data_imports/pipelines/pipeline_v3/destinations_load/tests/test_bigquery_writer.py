import io
from collections.abc import AsyncIterator

import pytest
from unittest.mock import MagicMock

import pyarrow as pa
import pyarrow.parquet as pq
from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import (
    DestinationBatchContext,
    DestinationRunContext,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.tests.fake_bigquery import (
    FakeBigQueryClient,
    MergeMultiMatchError,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.bigquery import (
    _OWNERSHIP_LABEL_KEY,
    BigQueryDestinationConfigurationError,
    BigQueryDestinationWriter,
    UnrelatedTableExistsError,
    staging_table_name,
)


def _ctx(
    schema_id: str = "schema",
    sync_type: str = "full_refresh",
    primary_keys: tuple[str, ...] = (),
    run_uuid: str = "run-a1",
) -> DestinationRunContext:
    return DestinationRunContext(
        team_id=1,
        schema_id=schema_id,
        source_id="source",
        job_id="job",
        run_uuid=run_uuid,
        destination_id="destination",
        destination_type="BigQuery",
        destination_name="test bigquery",
        table_name="charges",
        sync_type=sync_type,
        primary_keys=primary_keys,
        config={"project": "proj", "dataset": "dataset"},
    )


def _table(labels: dict | None = None) -> MagicMock:
    table = MagicMock()
    table.labels = labels
    return table


class LocalBigQueryWriter(BigQueryDestinationWriter):
    """Points the writer at an in-memory BigQuery instead of a customer's project."""

    def __init__(self, ctx: DestinationRunContext, client: FakeBigQueryClient) -> None:
        super().__init__(ctx)
        self._fake = client

    def _get_client(self) -> bigquery.Client:
        return self._fake  # type: ignore[return-value]  # ty: ignore[invalid-return-type]


async def _batches(*record_batches: pa.RecordBatch) -> AsyncIterator[pa.RecordBatch]:
    for batch in record_batches:
        yield batch


def _rows(ids: list[int], names: list[str]) -> pa.RecordBatch:
    return pa.RecordBatch.from_pydict({"id": ids, "name": names})


def _parquet(batch: pa.RecordBatch) -> io.BytesIO:
    buffer = io.BytesIO()
    pq.write_table(pa.Table.from_batches([batch]), buffer)
    buffer.seek(0)
    return buffer


def _read(client: FakeBigQueryClient, table: str = "charges") -> list[tuple]:
    rows = client.get_table(f"proj.dataset.{table}").rows
    return sorted((row["id"], row["name"]) for row in rows)


async def _deliver(
    writer: BigQueryDestinationWriter,
    ctx: DestinationRunContext,
    batch: pa.RecordBatch,
    batch_index: int,
    *,
    is_final: bool = False,
) -> None:
    await writer.prepare_run(ctx)
    await writer.write_batch(
        _batches(batch), DestinationBatchContext(run=ctx, batch_index=batch_index, is_final_batch=is_final)
    )
    if is_final:
        await writer.finalize_run(ctx)


class TestSchemaLabel:
    def test_the_same_schema_id_always_hashes_to_the_same_label(self) -> None:
        writer = BigQueryDestinationWriter(_ctx("schema-a"))

        assert writer._schema_label() == writer._schema_label()

    def test_different_schema_ids_hash_to_different_labels(self) -> None:
        first = BigQueryDestinationWriter(_ctx("schema-a"))
        second = BigQueryDestinationWriter(_ctx("schema-b"))

        assert first._schema_label() != second._schema_label()

    def test_the_label_only_uses_characters_bigquery_labels_allow(self) -> None:
        # Lowercase letters, digits, underscores and dashes only, at most 63 bytes — unlike
        # `schema_id` itself, which carries no such guarantee.
        writer = BigQueryDestinationWriter(_ctx("Schema/With Odd Characters!"))
        label = writer._schema_label()

        assert len(label.encode()) <= 63
        assert all(c.islower() or c.isdigit() or c in "_-" for c in label)


class TestCheckOwnedOrAbsent:
    def test_a_table_that_does_not_exist_is_reported_absent(self) -> None:
        writer = BigQueryDestinationWriter(_ctx())
        client = MagicMock()
        client.get_table.side_effect = NotFound("no such table")

        assert writer._check_owned_or_absent(client, "proj.dataset.charges", "write to it") is True

    def test_a_table_this_schema_marked_owned_is_reported_present_but_not_absent(self) -> None:
        writer = BigQueryDestinationWriter(_ctx("schema-a"))
        client = MagicMock()
        client.get_table.return_value = _table({_OWNERSHIP_LABEL_KEY: writer._schema_label()})

        assert writer._check_owned_or_absent(client, "proj.dataset.charges", "write to it") is False

    def test_a_table_with_no_labels_at_all_raises(self) -> None:
        writer = BigQueryDestinationWriter(_ctx())
        client = MagicMock()
        client.get_table.return_value = _table(None)

        with pytest.raises(UnrelatedTableExistsError):
            writer._check_owned_or_absent(client, "proj.dataset.charges", "write to it")

    def test_a_table_owned_by_a_different_schema_raises(self) -> None:
        writer = BigQueryDestinationWriter(_ctx("schema-a"))
        other = BigQueryDestinationWriter(_ctx("schema-b"))
        client = MagicMock()
        client.get_table.return_value = _table({_OWNERSHIP_LABEL_KEY: other._schema_label()})

        with pytest.raises(UnrelatedTableExistsError):
            writer._check_owned_or_absent(client, "proj.dataset.charges", "write to it")


class TestMarkOwned:
    def test_marking_a_table_owned_preserves_its_other_labels(self) -> None:
        writer = BigQueryDestinationWriter(_ctx("schema-a"))
        client = MagicMock()
        client.get_table.return_value = _table({"team": "data"})

        writer._mark_owned(client, "proj.dataset.charges")

        (updated_table, fields), _kwargs = client.update_table.call_args
        assert fields == ["labels"]
        assert updated_table.labels == {"team": "data", _OWNERSHIP_LABEL_KEY: writer._schema_label()}


class TestConfigValidation:
    def test_a_destination_with_no_dataset_is_rejected_before_a_batch_is_read(self) -> None:
        ctx = DestinationRunContext(
            team_id=1,
            schema_id="schema",
            source_id="source",
            job_id="job",
            run_uuid="run-a1",
            destination_id="destination",
            destination_type="BigQuery",
            destination_name="test bigquery",
            table_name="charges",
            sync_type="full_refresh",
            config={"project": "proj"},
        )

        with pytest.raises(BigQueryDestinationConfigurationError):
            BigQueryDestinationWriter(ctx)


@pytest.mark.asyncio
class TestFullRefresh:
    async def test_the_live_table_only_changes_once_the_run_completes(self) -> None:
        client = FakeBigQueryClient()
        ctx = _ctx()
        writer = LocalBigQueryWriter(ctx, client)

        await _deliver(writer, ctx, _rows([1], ["a"]), 0)
        with pytest.raises(NotFound):
            client.get_table("proj.dataset.charges")

        await _deliver(writer, ctx, _rows([2], ["b"]), 1, is_final=True)

        assert _read(client) == [(1, "a"), (2, "b")]

    async def test_reapplying_a_batch_does_not_duplicate_its_rows(self) -> None:
        # Without the batch-index stamp only batch 0 truncated, so re-applying any later batch
        # appended a second copy of its rows to the staging table.
        client = FakeBigQueryClient()
        ctx = _ctx()
        writer = LocalBigQueryWriter(ctx, client)

        await _deliver(writer, ctx, _rows([1], ["a"]), 0)
        await _deliver(writer, ctx, _rows([2], ["b"]), 1)
        await _deliver(writer, ctx, _rows([2], ["b"]), 1)
        await _deliver(writer, ctx, _rows([3], ["c"]), 2, is_final=True)

        assert _read(client) == [(1, "a"), (2, "b"), (3, "c")]

    async def test_replaying_the_published_final_batch_keeps_the_earlier_batches(self) -> None:
        # Without the publish stamp this replays as "rebuild a staging table from one batch,
        # then copy it over the finished table", leaving only the final batch's rows.
        client = FakeBigQueryClient()
        ctx = _ctx()
        writer = LocalBigQueryWriter(ctx, client)

        await _deliver(writer, ctx, _rows([1, 2], ["a", "b"]), 0)
        await _deliver(writer, ctx, _rows([3], ["c"]), 1, is_final=True)
        assert _read(client) == [(1, "a"), (2, "b"), (3, "c")]

        await _deliver(writer, ctx, _rows([3], ["c"]), 1, is_final=True)

        assert _read(client) == [(1, "a"), (2, "b"), (3, "c")]

    async def test_the_published_table_does_not_carry_the_batch_index_column(self) -> None:
        # The column is the staging table's own bookkeeping, and a synced table is supposed to
        # mirror its source.
        client = FakeBigQueryClient()
        ctx = _ctx()
        writer = LocalBigQueryWriter(ctx, client)

        await _deliver(writer, ctx, _rows([1], ["a"]), 0, is_final=True)

        assert client.get_table("proj.dataset.charges").columns == ["id", "name"]

    async def test_a_run_that_never_finishes_leaves_the_previous_data_in_place(self) -> None:
        client = FakeBigQueryClient()
        first = _ctx(run_uuid="run-a1")
        await _deliver(LocalBigQueryWriter(first, client), first, _rows([1], ["old"]), 0, is_final=True)

        second = _ctx(run_uuid="run-b2")
        await _deliver(LocalBigQueryWriter(second, client), second, _rows([2], ["new"]), 0)
        # `abort_destinations` builds a fresh writer, so cleanup has to run on one that has
        # never connected.
        await LocalBigQueryWriter(second, client).abort_run(second)

        assert _read(client) == [(1, "old")]
        with pytest.raises(NotFound):
            client.get_table(f"proj.dataset.{staging_table_name(second)}")


@pytest.mark.asyncio
class TestIncremental:
    async def test_the_first_run_of_an_incremental_schema_creates_its_merge_target(self) -> None:
        # A schema is on sync_type "incremental" from its very first run, and nothing else
        # creates the table the MERGE needs, so without this the first sync could never land.
        client = FakeBigQueryClient()
        ctx = _ctx(sync_type="incremental", primary_keys=("id",))
        writer = LocalBigQueryWriter(ctx, client)

        await _deliver(writer, ctx, _rows([1, 2], ["a", "b"]), 0, is_final=True)

        assert _read(client) == [(1, "a"), (2, "b")]

    async def test_rows_are_merged_on_the_primary_key(self) -> None:
        client = FakeBigQueryClient()
        ctx = _ctx(sync_type="incremental", primary_keys=("id",))
        writer = LocalBigQueryWriter(ctx, client)

        await _deliver(writer, ctx, _rows([1, 2], ["first", "second"]), 0)
        await _deliver(writer, ctx, _rows([1], ["updated"]), 1, is_final=True)

        assert _read(client) == [(1, "updated"), (2, "second")]

    async def test_a_batch_carrying_one_key_twice_keeps_the_last_row(self) -> None:
        # Nothing upstream promises a staged batch holds each key once, and BigQuery rejects a
        # MERGE whose source matches a target row more than once — on every retry.
        client = FakeBigQueryClient()
        ctx = _ctx(sync_type="incremental", primary_keys=("id",))
        writer = LocalBigQueryWriter(ctx, client)

        await _deliver(writer, ctx, _rows([1], ["first"]), 0)
        await _deliver(writer, ctx, _rows([1, 1], ["stale", "latest"]), 1, is_final=True)

        assert _read(client) == [(1, "latest")]

    async def test_the_fake_rejects_a_duplicated_key_the_way_bigquery_does(self) -> None:
        # Guards the test above: if the fake accepted a multi-matching MERGE, that test would
        # pass with or without the dedup.
        client = FakeBigQueryClient()
        client.load_table_from_file(
            _parquet(_rows([1], ["first"])),
            "proj.dataset.charges",
            bigquery.LoadJobConfig(write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE),
        )
        client.load_table_from_file(
            _parquet(_rows([1, 1], ["stale", "latest"])),
            "proj.dataset.source",
            bigquery.LoadJobConfig(write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE),
        )

        with pytest.raises(MergeMultiMatchError):
            client.query(
                "MERGE `proj.dataset.charges` T USING `proj.dataset.source` S ON T.`id` = S.`id` "
                "WHEN MATCHED THEN UPDATE SET T.`name` = S.`name` "
                "WHEN NOT MATCHED THEN INSERT (`id`, `name`) VALUES (S.`id`, S.`name`)"
            )
