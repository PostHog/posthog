import io
from collections.abc import AsyncIterator

import pytest
from unittest.mock import MagicMock

import pyarrow as pa
import pyarrow.parquet as pq
from google.api_core.exceptions import BadRequest, Forbidden, NotFound, ServiceUnavailable
from google.auth.exceptions import RefreshError
from google.cloud import bigquery
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import (
    DestinationBatchContext,
    DestinationRunContext,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.errors import (
    DestinationConfigurationError,
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
    _ddl_type,
    staging_table_name,
)

_IMPERSONATION_DENIED_BODY = (
    '{"error": {"code": 403, "message": "Permission \'iam.serviceAccounts.getAccessToken\' denied on resource '
    '(or it may not exist).", "status": "PERMISSION_DENIED"}}'
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


class TestDdlType:
    @parameterized.expand(
        [
            ("STRING", "STRING"),
            # The legacy names `get_table` reports have no DDL alias for FLOAT, unlike INTEGER
            # (INT64) and BOOLEAN (BOOL) — an unmapped FLOAT fails the ALTER TABLE outright.
            ("INTEGER", "INT64"),
            ("FLOAT", "FLOAT64"),
            ("BOOLEAN", "BOOL"),
        ]
    )
    def test_a_scalar_field_renders_its_standard_sql_type(self, field_type: str, expected: str) -> None:
        assert _ddl_type(bigquery.SchemaField("clicks", field_type)) == expected

    def test_a_repeated_field_renders_as_an_array(self) -> None:
        # Dropping `mode` here would add the element type as a scalar column, which is
        # incompatible with the array BigQuery already autodetected for the scratch table.
        field = bigquery.SchemaField("tags", "STRING", mode="REPEATED")

        assert _ddl_type(field) == "ARRAY<STRING>"

    def test_a_record_field_renders_as_a_struct_of_its_subfields(self) -> None:
        # A bare `RECORD` is not valid DDL; the subfields must be spelled out.
        field = bigquery.SchemaField(
            "address",
            "RECORD",
            fields=[bigquery.SchemaField("city", "STRING"), bigquery.SchemaField("zip", "INTEGER")],
        )

        assert _ddl_type(field) == "STRUCT<`city` STRING, `zip` INT64>"

    def test_a_repeated_record_field_renders_as_an_array_of_structs(self) -> None:
        field = bigquery.SchemaField(
            "addresses", "RECORD", mode="REPEATED", fields=[bigquery.SchemaField("city", "STRING")]
        )

        assert _ddl_type(field) == "ARRAY<STRUCT<`city` STRING>>"


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
    @pytest.mark.parametrize(
        "denial",
        [
            RefreshError("Unable to acquire impersonated credentials", _IMPERSONATION_DENIED_BODY),
            # The same refusal raised inside a gRPC auth plugin, which reaches the caller as a 503.
            ServiceUnavailable(
                f"Getting metadata from plugin failed with error: "
                f"('Unable to acquire impersonated credentials', '{_IMPERSONATION_DENIED_BODY}')"
            ),
        ],
        ids=["rest", "grpc"],
    )
    async def test_a_service_account_posthog_cannot_impersonate_is_a_configuration_error(
        self, denial: Exception
    ) -> None:
        client = FakeBigQueryClient()
        client.create_dataset = MagicMock(side_effect=denial)  # type: ignore[method-assign]
        writer = LocalBigQueryWriter(_ctx(), client)

        with pytest.raises(DestinationConfigurationError, match="Token Creator"):
            await writer.prepare_run(_ctx())

    @pytest.mark.asyncio
    async def test_a_service_account_missing_an_iam_permission_is_a_configuration_error(self) -> None:
        client = FakeBigQueryClient()
        client.create_dataset = MagicMock(  # type: ignore[method-assign]
            side_effect=Forbidden(
                "Access Denied: Project proj: User does not have bigquery.datasets.create permission in project proj."
            )
        )
        writer = LocalBigQueryWriter(_ctx(), client)

        with pytest.raises(DestinationConfigurationError, match="Data Editor"):
            await writer.prepare_run(_ctx())


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

    async def test_a_column_sent_as_text_merges_into_its_int64_column(self) -> None:
        client = FakeBigQueryClient()
        ctx = _ctx(sync_type="incremental", primary_keys=("id",))
        writer = LocalBigQueryWriter(ctx, client)

        await _deliver(writer, ctx, pa.RecordBatch.from_pydict({"id": [1], "delivered_at": [1700000000]}), 0)
        await _deliver(
            writer,
            ctx,
            pa.RecordBatch.from_pydict({"id": [1, 2], "delivered_at": ["1700000500", None]}),
            1,
            is_final=True,
        )

        table = client.get_table("proj.dataset.charges")
        assert table.types["delivered_at"] == "INTEGER"
        assert sorted((row["id"], row["delivered_at"]) for row in table.rows) == [(1, 1700000500), (2, None)]

    @parameterized.expand(
        [
            ("clicks", 10),
            # Regression: FLOAT64 has no "FLOAT" DDL alias, so adding a float column here used
            # to fail the ALTER TABLE with "Type not found: FLOAT" before `_evolve_table`
            # normalized the legacy type name `get_table` reports.
            ("rate", 0.5),
        ]
    )
    async def test_a_column_a_later_batch_grows_is_added_to_the_target_before_merging(
        self, column: str, value: float
    ) -> None:
        # MERGE does not evolve schema on its own, so a column only the second batch carries
        # must be added to the target first, or the MERGE fails referencing a column T lacks.
        client = FakeBigQueryClient()
        ctx = _ctx(sync_type="incremental", primary_keys=("id",))
        writer = LocalBigQueryWriter(ctx, client)

        await _deliver(writer, ctx, _rows([1], ["a"]), 0)
        await _deliver(
            writer,
            ctx,
            pa.RecordBatch.from_pydict({"id": [2], "name": ["b"], column: [value]}),
            1,
            is_final=True,
        )

        table = client.get_table("proj.dataset.charges")
        assert table.columns == ["id", "name", column]
        assert sorted((row["id"], row["name"], row.get(column)) for row in table.rows) == [
            (1, "a", None),
            (2, "b", value),
        ]

    def test_the_fake_rejects_a_ddl_type_with_no_alias_the_way_bigquery_does(self) -> None:
        # Guards the float case above: if the fake accepted FLOAT in an ALTER TABLE, that case
        # would pass with or without `_ddl_type` normalizing it to FLOAT64 first.
        client = FakeBigQueryClient()
        client.load_table_from_file(
            _parquet(_rows([1], ["a"])),
            "proj.dataset.charges",
            bigquery.LoadJobConfig(write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE),
        )

        with pytest.raises(BadRequest, match="FLOAT"):
            client.query("ALTER TABLE `proj.dataset.charges` ADD COLUMN IF NOT EXISTS `rate` FLOAT")

    async def test_text_that_cannot_convert_to_the_int64_column_is_a_configuration_error(self) -> None:
        # A retry sends the same values, so a retryable error would fail until someone changes the table.
        client = FakeBigQueryClient()
        ctx = _ctx(sync_type="incremental", primary_keys=("id",))
        writer = LocalBigQueryWriter(ctx, client)

        await _deliver(writer, ctx, pa.RecordBatch.from_pydict({"id": [1], "delivered_at": [1700000000]}), 0)

        with pytest.raises(DestinationConfigurationError, match="delivered_at"):
            await _deliver(writer, ctx, pa.RecordBatch.from_pydict({"id": [1], "delivered_at": ["soon"]}), 1)


@pytest.mark.asyncio
class TestAppend:
    """sync_type "incremental" with no primary keys: plain `WRITE_APPEND`, no `MERGE`."""

    async def test_a_whole_number_float_appends_without_changing_the_int64_column(self) -> None:
        # Regression: the append path used to load the raw batch straight through, so a column
        # BigQuery had autodetected as INTEGER on an earlier batch failed the whole load job as
        # soon as a later batch sent it as a float, even when every value still fit as a whole
        # number. The merge path already aligned to the target's type before this writer existed
        # for plain appends.
        client = FakeBigQueryClient()
        ctx = _ctx(sync_type="incremental")
        writer = LocalBigQueryWriter(ctx, client)

        await _deliver(writer, ctx, pa.RecordBatch.from_pydict({"id": [1], "count": [1]}), 0)
        await _deliver(writer, ctx, pa.RecordBatch.from_pydict({"id": [2], "count": [2.0]}), 1, is_final=True)

        table = client.get_table("proj.dataset.charges")
        assert table.types["count"] == "INTEGER"
        assert sorted(row["count"] for row in table.rows) == [1, 2]

    async def test_a_fractional_value_that_cannot_fit_the_int64_column_is_a_configuration_error(self) -> None:
        # A retry sends the same values, so a retryable error would fail until someone widens
        # the column in BigQuery to FLOAT64.
        client = FakeBigQueryClient()
        ctx = _ctx(sync_type="incremental")
        writer = LocalBigQueryWriter(ctx, client)

        await _deliver(writer, ctx, pa.RecordBatch.from_pydict({"id": [1], "rate": [1]}), 0)

        with pytest.raises(DestinationConfigurationError, match="rate"):
            await _deliver(writer, ctx, pa.RecordBatch.from_pydict({"id": [2], "rate": [0.5]}), 1)

    async def test_a_number_other_than_0_or_1_cannot_convert_to_the_bool_column(self) -> None:
        # Regression: `pc.cast` treats any nonzero number as truthy rather than raising, unlike
        # its float-to-int64 cast, so aligning to a BOOL target used to silently turn 2 into true
        # instead of raising the way a direct append to BigQuery always did.
        client = FakeBigQueryClient()
        ctx = _ctx(sync_type="incremental")
        writer = LocalBigQueryWriter(ctx, client)

        await _deliver(writer, ctx, pa.RecordBatch.from_pydict({"id": [1], "active": [True]}), 0)

        with pytest.raises(DestinationConfigurationError, match="active"):
            await _deliver(writer, ctx, pa.RecordBatch.from_pydict({"id": [2], "active": [2]}), 1)
