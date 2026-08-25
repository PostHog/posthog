import uuid

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.db import OperationalError, transaction

from asgiref.sync import async_to_sync
from clickhouse_driver.errors import ServerException
from parameterized import parameterized

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import (
    build_table_name,
    resolve_table_and_folder_names,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_sync import (
    _refresh_cumulative_row_count,
    merge_columns,
    update_last_synced_at,
    validate_schema_and_update_table,
)

_PIPELINE_SYNC_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_sync"
_DB_RETRY_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.common.db_retry"
_TABLE_MODULE = "products.warehouse_sources.backend.models.table"


class TestResolveTableAndFolderNames:
    @parameterized.expand(
        [
            # Stripe CamelCase: folder snake_cases, but the table keeps the only-lowercased raw name.
            (
                "stripe_camelcase",
                "BalanceTransaction",
                "balance_transaction",
                "BalanceTransaction",
                "balance_transaction",
            ),
            (
                "stripe_compound",
                "CustomerBalanceTransaction",
                "customer_balance_transaction",
                "CustomerBalanceTransaction",
                "customer_balance_transaction",
            ),
            # Already snake_case: table and folder match.
            ("plain_snake", "charge", "charge", "charge", "charge"),
            # Native multi-schema (never migrated): dotted name drives the table, folder snake_cases the dot.
            ("native_multi_schema", "public.orders", "public_orders", "public.orders", "public_orders"),
            # Legacy migrated row: folder is pinned to the original (differs from normalize(name)),
            # so the table anchors to the pinned folder, not the qualified name.
            ("legacy_pinned", "public.users", "users", "users", "users"),
            # No folder set: behaves like a plain row, table from the raw name.
            ("no_folder", "BalanceTransaction", None, "BalanceTransaction", "balance_transaction"),
        ]
    )
    def test_resolve(
        self, _name: str, schema_name: str, resolved_folder: str | None, exp_table: str, exp_folder: str
    ) -> None:
        names = resolve_table_and_folder_names(schema_name, resolved_folder)
        assert names.table_storage_name == exp_table
        assert names.folder_name == exp_folder

    def test_table_name_unchanged_for_camelcase_source(self) -> None:
        # The regression guard: a populated (snake_cased) folder must NOT rename the HogQL table.
        source = ExternalDataSource(source_type="Stripe", prefix="")
        names = resolve_table_and_folder_names("BalanceTransaction", "balance_transaction")
        assert build_table_name(source, names.table_storage_name) == "stripe_balancetransaction"

    @parameterized.expand(
        [
            # Repo-qualified GitHub rows: the slash must flatten (it's not a valid identifier
            # char anywhere downstream) while the dot dunders like SQL multi-schema — yielding
            # HogQL `github.posthog_posthog__issues`. A bare slash surviving here produces an
            # unqueryable table name.
            ("github_qualified", "GitHub", "posthog/posthog.issues", "github_posthog_posthog__issues"),
            ("github_legacy_bare", "GitHub", "issues", "github_issues"),
            ("github_dotted_repo", "GitHub", "posthog/next.js.issues", "github_posthog_next__js__issues"),
        ]
    )
    def test_build_table_name_flattens_repo_qualifiers(
        self, _name: str, source_type: str, schema_name: str, expected: str
    ) -> None:
        source = ExternalDataSource(source_type=source_type, prefix="")
        names = resolve_table_and_folder_names(schema_name, None)
        assert build_table_name(source, names.table_storage_name) == expected


class TestRefreshCumulativeRowCount:
    def test_updates_row_count_on_success(self) -> None:
        table = MagicMock(row_count=1)
        table.get_count.return_value = 42

        _refresh_cumulative_row_count(table, MagicMock(), "orders (schema-1)")

        assert table.row_count == 42

    def test_keeps_previous_row_count_when_get_count_fails(self) -> None:
        # get_count() raises when both the chdb and ClickHouse-cluster reads of the S3 dataset
        # time out on a large table. That's a display stat, not the synced data — it must not
        # propagate and fail the whole table registration for an otherwise-successful sync.
        table = MagicMock(row_count=7)
        table.get_count.side_effect = Exception(
            "Reading the files from your storage bucket took too long and the query was cancelled."
        )
        logger = MagicMock()

        _refresh_cumulative_row_count(table, logger, "orders (schema-1)")

        assert table.row_count == 7
        logger.warning.assert_called_once()


def _register_companion_sync(
    run_id: str,
    team_id: int,
    schema_id: uuid.UUID,
    resource_name: str,
    row_count: int,
    table_format: DataWarehouseTable.TableFormat,
    queryable_folder: str,
    table_schema_dict: dict[str, str] | None = None,
    set_as_schema_table: bool = False,
) -> None:
    """Synchronous version of register_cdc_companion_table for testing.

    Mirrors the inner _register() logic without the async/database_sync_to_async_pool wrapper.
    """
    if row_count == 0:
        return

    job = ExternalDataJob.objects.prefetch_related("pipeline").get(pk=run_id)
    normalized_resource_name = NamingConvention.normalize_identifier(resource_name)
    companion_table_name = build_table_name(job.pipeline, resource_name)
    new_url_pattern = job.url_pattern_by_schema(normalized_resource_name)

    table_params = {
        "name": companion_table_name,
        "format": table_format,
        "url_pattern": new_url_pattern,
        "team_id": team_id,
        "row_count": row_count,
        "queryable_folder": queryable_folder,
    }

    companion_table: DataWarehouseTable | None = DataWarehouseTable.objects.filter(
        team_id=team_id,
        name=companion_table_name,
        external_data_source_id=job.pipeline.id,
        deleted=False,
    ).first()

    if companion_table:
        companion_table.format = table_format
        companion_table.url_pattern = new_url_pattern
        companion_table.queryable_folder = queryable_folder
        companion_table.row_count = companion_table.get_count()
        companion_table.save(update_fields=["format", "url_pattern", "queryable_folder", "row_count"])
    else:
        companion_table = DataWarehouseTable.objects.create(external_data_source_id=job.pipeline.id, **table_params)

    raw_db_columns = companion_table.get_columns()
    db_columns = {key: str(column.get("clickhouse", "")) for key, column in raw_db_columns.items()}
    existing_columns = companion_table.columns or {}
    columns = merge_columns(db_columns, table_schema_dict or {}, existing_columns)

    with transaction.atomic():
        companion_table.columns = columns
        companion_table.save(update_fields=["columns"])

        if set_as_schema_table:
            ExternalDataSchema.objects.filter(id=schema_id, team_id=team_id).update(table=companion_table)


class TestRegisterCDCCompanionTable(BaseTest):
    def _create_source_and_job(self) -> tuple[ExternalDataSource, ExternalDataJob, ExternalDataSchema]:
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Stripe",
            created_by=self.user,
            job_inputs={"stripe_secret_key": "sk_test_123"},
        )
        schema = ExternalDataSchema.objects.create(
            name="orders",
            team_id=self.team.pk,
            source=source,
        )
        job = ExternalDataJob.objects.create(
            team_id=self.team.pk,
            pipeline=source,
            schema=schema,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=0,
        )
        return source, job, schema

    @patch.object(DataWarehouseTable, "get_columns", return_value={})
    @patch.object(DataWarehouseTable, "get_count", return_value=100)
    def test_creates_companion_table(self, _mock_count, _mock_cols):
        source, job, schema = self._create_source_and_job()

        _register_companion_sync(
            run_id=str(job.id),
            team_id=self.team.pk,
            schema_id=schema.id,
            resource_name="orders_cdc",
            row_count=100,
            table_format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            queryable_folder="s3://bucket/cdc_folder",
            table_schema_dict={"id": "Int64", "name": "String"},
        )

        companion = DataWarehouseTable.objects.filter(
            team_id=self.team.pk,
            external_data_source_id=source.pk,
            deleted=False,
        ).exclude(id__in=[schema.table_id] if schema.table_id else [])

        assert companion.count() == 1
        table = companion.first()
        assert table is not None
        assert table.name.endswith("orders_cdc")
        assert table.queryable_folder == "s3://bucket/cdc_folder"

    @patch.object(DataWarehouseTable, "get_columns", return_value={})
    @patch.object(DataWarehouseTable, "get_count", return_value=200)
    def test_updates_existing_companion_table(self, _mock_count, _mock_cols):
        source, job, schema = self._create_source_and_job()

        _register_companion_sync(
            run_id=str(job.id),
            team_id=self.team.pk,
            schema_id=schema.id,
            resource_name="orders_cdc",
            row_count=100,
            table_format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            queryable_folder="s3://bucket/cdc_folder_v1",
        )

        _register_companion_sync(
            run_id=str(job.id),
            team_id=self.team.pk,
            schema_id=schema.id,
            resource_name="orders_cdc",
            row_count=200,
            table_format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            queryable_folder="s3://bucket/cdc_folder_v2",
        )

        companions = DataWarehouseTable.objects.filter(
            team_id=self.team.pk,
            external_data_source_id=source.pk,
            deleted=False,
        ).exclude(id__in=[schema.table_id] if schema.table_id else [])

        assert companions.count() == 1
        table = companions.first()
        assert table is not None
        assert table.queryable_folder == "s3://bucket/cdc_folder_v2"

    @patch.object(DataWarehouseTable, "get_columns", return_value={})
    @patch.object(DataWarehouseTable, "get_count", return_value=50)
    def test_set_as_schema_table_links_companion_to_schema(self, _mock_count, _mock_cols):
        source, job, schema = self._create_source_and_job()
        assert schema.table is None

        _register_companion_sync(
            run_id=str(job.id),
            team_id=self.team.pk,
            schema_id=schema.id,
            resource_name="orders_cdc",
            row_count=50,
            table_format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            queryable_folder="s3://bucket/cdc_folder",
            set_as_schema_table=True,
        )

        schema.refresh_from_db()
        table_name = getattr(schema.table, "name", None)
        assert table_name is not None
        assert table_name.endswith("orders_cdc")

    def test_skips_zero_rows(self):
        source, job, schema = self._create_source_and_job()

        _register_companion_sync(
            run_id=str(job.id),
            team_id=self.team.pk,
            schema_id=schema.id,
            resource_name="orders_cdc",
            row_count=0,
            table_format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            queryable_folder="s3://bucket/cdc_folder",
        )

        companions = DataWarehouseTable.objects.filter(
            team_id=self.team.pk,
            external_data_source_id=source.pk,
            deleted=False,
        )
        assert companions.count() == 0


# transaction=True: validate_schema_and_update_table writes to the DB from the async thread pool
# (database_sync_to_async_pool), which can't see an atomic TestCase's uncommitted rows.
@pytest.mark.django_db(transaction=True)
class TestValidateSchemaAndUpdateTable:
    def _schema_and_job(self, team) -> tuple[ExternalDataSchema, ExternalDataJob]:
        source = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()), connection_id=str(uuid.uuid4()), team=team, source_type="Postgres"
        )
        schema = ExternalDataSchema.objects.create(name="orders", team=team, source=source)
        job = ExternalDataJob.objects.create(
            team=team, pipeline=source, schema=schema, status=ExternalDataJob.Status.RUNNING, rows_synced=10
        )
        return schema, job

    def test_delta_table_with_no_committed_files_does_not_crash_the_sync(self, team):
        # A Delta table can pass load.py's "does a table exist" check while still having zero
        # committed add-file actions (e.g. an incremental run that wrote no new rows). ClickHouse then
        # raises DELTA_KERNEL_ERROR ("No files in log segment") when get_columns() tries to DESCRIBE
        # it. This must be tolerated like the sibling CANNOT_EXTRACT_TABLE_STRUCTURE (636) case rather
        # than crash the whole sync activity - regression for a real production failure where it did.
        schema, job = self._schema_and_job(team)
        no_files_error = ServerException(
            "DB::Exception: Received DeltaLake kernel error GenericError: Generic delta kernel error: "
            "No files in log segment (in snapshot).",
            code=742,
        )

        with (
            patch(f"{_TABLE_MODULE}.sync_execute", side_effect=no_files_error),
            patch(f"{_TABLE_MODULE}.time.sleep"),
        ):
            async_to_sync(validate_schema_and_update_table)(
                run_id=str(job.id),
                team_id=team.pk,
                schema_id=schema.id,
                row_count=10,
                table_format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
                queryable_folder="s3://bucket/orders",
            )

        schema.refresh_from_db()
        # get_columns() failing means the table never gets linked to the schema or given columns -
        # but critically, the sync activity itself must survive rather than crash the whole run.
        assert schema.table is None
        table = DataWarehouseTable.objects.get(external_data_source=schema.source, deleted=False)
        assert not table.columns
        assert table.created_via == DataWarehouseTable.CreatedVia.SOURCE


class TestUpdateLastSyncedAt:
    @pytest.mark.asyncio
    async def test_retries_transient_query_wait_timeout_then_succeeds(self):
        # A saturated pgbouncer pool can reject either read with `query_wait_timeout` before the
        # query ever reaches Postgres, so retrying the whole lookup+save is safe and avoids
        # failing the whole import activity over a momentary blip.
        job = MagicMock()
        get_job = MagicMock(side_effect=[OperationalError("query_wait_timeout"), job])
        schema = MagicMock()
        get_schema = MagicMock(return_value=schema)

        with (
            patch(f"{_PIPELINE_SYNC_MODULE}.ExternalDataJob.objects.get", get_job),
            patch(
                f"{_PIPELINE_SYNC_MODULE}.ExternalDataSchema.objects.exclude", return_value=MagicMock(get=get_schema)
            ),
            patch(f"{_DB_RETRY_MODULE}.close_old_connections") as close,
            patch(f"{_DB_RETRY_MODULE}.time.sleep") as sleep,
        ):
            await update_last_synced_at(job_id="job-1", schema_id="schema-1", team_id=1)

        assert get_job.call_count == 2
        assert schema.last_synced_at == job.created_at
        schema.save.assert_called_once_with(skip_activity_log=True)
        close.assert_called_once()
        sleep.assert_called_once_with(2)


class TestSetInitialSyncComplete(BaseTest):
    """The purge-then-flip contract: a CDC snapshot schema's buffer prefix is purged before the
    streaming flip (stale pre-snapshot files merged after the flip resurrect rows the snapshot
    wiped), and NEVER purged when the schema is already streaming (those files are live,
    unconsumed changes)."""

    def _schema(self, *, sync_type: str, config: dict, initial_sync_complete: bool) -> ExternalDataSchema:
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status="Completed",
            source_type="Postgres",
        )
        return ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source=source,
            name="public.users",
            sync_type=sync_type,
            sync_type_config=config,
            initial_sync_complete=initial_sync_complete,
        )

    @parameterized.expand(
        [
            # The flip: stale buffer must be gone before streaming resumes.
            ("cdc_snapshot_first_completion", "cdc", {"cdc_mode": "snapshot"}, False, True, "streaming"),
            # Already streaming (idempotent completion call): purging would delete live files.
            ("cdc_already_streaming", "cdc", {"cdc_mode": "streaming"}, True, False, "streaming"),
            # Non-CDC schemas have no buffer; purge must not run.
            ("non_cdc", "full_refresh", {}, False, False, None),
        ]
    )
    def test_purges_buffer_only_on_snapshot_to_streaming_flip(
        self,
        _name: str,
        sync_type: str,
        config: dict,
        initial_flag: bool,
        expects_purge: bool,
        expected_cdc_mode: str | None,
    ) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_sync import (
            _purge_stale_buffer_then_mark_initial_sync_complete,
        )

        schema = self._schema(sync_type=sync_type, config=config, initial_sync_complete=initial_flag)
        calls: list[str] = []

        def _record_purge(team_id: int, schema_id: str, logger, *, strict: bool = False) -> None:
            assert strict, "flip purge must be strict — a swallowed failure re-ships the phantom-row bug"
            fresh = ExternalDataSchema.objects.get(id=schema_id)
            assert not fresh.initial_sync_complete, "purge must run BEFORE the flip commits"
            calls.append(schema_id)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.cdc.buffer.purge_buffer_prefix",
            side_effect=_record_purge,
        ):
            _purge_stale_buffer_then_mark_initial_sync_complete(str(schema.id), self.team.pk, MagicMock())

        schema.refresh_from_db()
        assert schema.initial_sync_complete is True
        assert (calls == [str(schema.id)]) is expects_purge
        assert schema.sync_type_config.get("cdc_mode") == expected_cdc_mode
