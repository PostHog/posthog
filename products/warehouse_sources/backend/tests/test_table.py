import subprocess
from typing import Any

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from clickhouse_driver.errors import ServerException
from parameterized import parameterized

from posthog.hogql.database.direct_clickhouse_table import DirectClickHouseTable
from posthog.hogql.database.models import DatabaseField, StringDatabaseField, UUIDDatabaseField
from posthog.hogql.database.s3_table import DataWarehouseTable as HogQLDataWarehouseTable

from posthog.exceptions import ClickHouseAtCapacity

from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import (
    DataWarehouseTable,
    get_hogql_field_for_column,
    run_chdb_query,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import (
    TransientObjectStoreError,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestHogQLDefinitionDirectDispatch(BaseTest):
    @parameterized.expand(
        [
            ("synced_clickhouse", ExternalDataSourceType.CLICKHOUSE, "warehouse", HogQLDataWarehouseTable),
            ("synced_clickhouse_cloud", ExternalDataSourceType.CLICKHOUSECLOUD, "warehouse", HogQLDataWarehouseTable),
            ("direct_clickhouse", ExternalDataSourceType.CLICKHOUSE, "direct", DirectClickHouseTable),
        ]
    )
    def test_clickhouse_table_class_respects_access_method(
        self,
        _name: str,
        source_type: str,
        access_method: str,
        expected_class: type,
    ) -> None:
        # A synced ClickHouse source's tables must stay S3-backed: a DirectSQLTable is
        # excluded from the printer's team_id-guard skip list, so resolving a synced table
        # as direct makes every ordinary query against it fail.
        source = ExternalDataSource(
            team=self.team,
            source_type=source_type,
            access_method=access_method,
            job_inputs={"database": "analytics"},
        )
        table = DataWarehouseTable(
            name="external_events",
            format="Parquet",
            team=self.team,
            url_pattern="s3://bucket/team_1/external_events",
            external_data_source=source,
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True}},
        )

        assert type(table.hogql_definition()) is expected_class


class TestDataWarehouseTableColumnOrder(BaseTest):
    def test_hogql_definition_honors_recorded_column_order(self) -> None:
        # A materialized-view backing table stores its columns in a jsonb object (order not
        # preserved) plus column_order (the physical/SELECT order). hogql_definition must expose
        # fields in recorded order so a materialized view's SELECT * matches the view's SELECT.
        table = DataWarehouseTable(
            name="my_matview",
            format="DeltaS3Wrapper",
            team=self.team,
            url_pattern="s3://bucket/team_1/modeling/my_matview",
            columns={
                "a": {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True},
                "zebra": {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True},
                "m": {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True},
            },
            column_order=["zebra", "a", "m"],
        )

        assert list(table.hogql_definition().fields.keys()) == ["zebra", "a", "m"]

    def test_set_columns_records_order(self) -> None:
        # The write-side chokepoint must set columns and column_order together so they cannot drift.
        table = DataWarehouseTable(name="t", format="DeltaS3Wrapper", team=self.team, url_pattern="s3://b/t")
        table.set_columns({"z": {"clickhouse": "String"}, "a": {"clickhouse": "String"}})

        assert table.column_order == ["z", "a"]


class TestWarehouseQueryDisablesHivePartitioning(BaseTest):
    # ClickHouse infers a type for each Hive-style partition-folder value it samples (e.g. our
    # internal `_ph_partition_key`) independently of the column's declared type. A table whose
    # partition granularity changed over time mixes value shapes across folders (e.g. an
    # hour-tier "2017-06-30T05" alongside older week-tier folders), and CH can misclassify the
    # column as Date and then fail to parse it — HogQLGlobalSettings disables this inference for
    # the normal HogQL query path, so these raw `sync_execute` calls must opt out the same way.
    def _table(self) -> DataWarehouseTable:
        return DataWarehouseTable(name="t", format="Delta", team=self.team, url_pattern="s3://bucket/team_1/t")

    def test_get_count_disables_hive_partitioning(self) -> None:
        with patch(
            "products.warehouse_sources.backend.models.table.sync_execute", return_value=[(5,)]
        ) as mock_sync_execute:
            count = self._table().get_count()

        assert count == 5
        assert mock_sync_execute.call_args.kwargs["settings"]["use_hive_partitioning"] == 0

    def test_get_max_value_for_column_disables_hive_partitioning(self) -> None:
        with patch(
            "products.warehouse_sources.backend.models.table.sync_execute", return_value=[(42,)]
        ) as mock_sync_execute:
            value = self._table().get_max_value_for_column("created_at")

        assert value == 42
        assert mock_sync_execute.call_args.kwargs["settings"]["use_hive_partitioning"] == 0


class TestSafeExposeChError:
    # ClickHouseAtCapacity is a DRF APIException with no `.message`, so the capacity check
    # must run before the message-matching loop — reordering them would reintroduce an
    # AttributeError on every capacity error during column introspection.
    @pytest.mark.parametrize("code", [202, 439])  # TOO_MANY_SIMULTANEOUS_QUERIES, CANNOT_SCHEDULE_TASK
    def test_capacity_errors_surface_as_clickhouse_at_capacity(self, code: int) -> None:
        with pytest.raises(ClickHouseAtCapacity):
            DataWarehouseTable()._safe_expose_ch_error(ServerException("busy", code=code))

    # A transient connection/read error (e.g. an EOFError from a dropped ClickHouse socket) is not
    # a ServerException, so wrap_clickhouse_query_error returns it untouched and it has no `.message`.
    # It must be re-raised as-is, not masked as a storage-bucket misconfiguration, which would hide
    # a retryable error from Temporal.
    @pytest.mark.parametrize(
        "err",
        [EOFError("Unexpected EOF while reading bytes"), ConnectionResetError("Connection reset by peer")],
    )
    def test_transient_errors_without_message_are_reraised_untouched(self, err: Exception) -> None:
        with pytest.raises(type(err)) as exc_info:
            DataWarehouseTable()._safe_expose_ch_error(err)
        assert exc_info.value is err

    def test_cancelled_query_gets_a_timeout_message_instead_of_storage_bucket_blame(self) -> None:
        # code 394 QUERY_WAS_CANCELLED here means our own client timed out reading, not bad files.
        with pytest.raises(Exception, match="took too long"):
            DataWarehouseTable()._safe_expose_ch_error(ServerException("DB::Exception: Query was cancelled.", code=394))

    def test_delta_kernel_permission_error_gets_actionable_message(self) -> None:
        # Delta-format tables (the default for every warehouse_sources synced table) read via
        # ClickHouse's DeltaLake kernel, whose object_store errors use different wording than
        # the native ClickHouse S3 errors above. Without a matching ExtractErrors entry this
        # fell through to the generic fallback message regardless of the actual cause.
        delta_kernel_error = ServerException(
            "DB::Exception: Received DeltaLake kernel error ObjectStoreError: Error interacting with "
            "object store: The operation lacked the necessary privileges to complete for path "
            "team_2_mysql_x/dw_table/_delta_log/_last_checkpoint: Error performing GET "
            "http://objectstorage:19000/data-warehouse/team_2_mysql_x/dw_table/_delta_log/_last_checkpoint "
            "- Server returned non-2xx status code: 403 Forbidden: AccessDenied",
            code=742,  # DELTA_KERNEL_ERROR
        )

        with pytest.raises(Exception, match="Access was denied when reading the provided file"):
            DataWarehouseTable()._safe_expose_ch_error(delta_kernel_error)

    @pytest.mark.parametrize(
        "raw_message,expected_action",
        [
            ("DB::Exception: Access Denied: while reading key: my-data/file.csv, S3 exception", "s3:GetObject"),
            ("DB::Exception: Could not list objects in bucket my-bucket, S3 exception", "s3:ListBucket"),
        ],
    )
    def test_native_s3_access_denials_name_the_iam_action_to_check(
        self, raw_message: str, expected_action: str
    ) -> None:
        # A self-managed S3 source reads and lists the customer's own bucket, so an access denial
        # is theirs to fix — name the exact IAM action rather than dead-ending on "access denied".
        with pytest.raises(Exception, match=expected_action):
            DataWarehouseTable()._safe_expose_ch_error(ServerException(raw_message, code=499))

    def test_delta_kernel_object_store_blip_is_retried_not_blamed_on_the_bucket(self) -> None:
        # ClickHouse's own deltaLake() S3 table function hits the same transient object-store
        # blips as delta-rs (e.g. a dropped connection to our own data-warehouse bucket), just
        # wrapped in a ClickHouse exception. Without this check it fell through to the generic
        # "check your credentials" message, which downstream code can no longer recognise as a
        # retryable infra blip (see is_transient_object_store_error) once it's a bare Exception.
        delta_kernel_error = ServerException(
            "DB::Exception: Received DeltaLake kernel error ObjectStoreError: Error interacting with "
            "object store: Generic S3 error: Error performing GET "
            "http://objectstorage:19000/data-warehouse/team_2_postgres_x/dw_table/_delta_log/_last_checkpoint "
            "in 6.1s, after 10 retries, max_retries: 10, retry_timeout: 180s - HTTP error: error sending request",
            code=742,  # DELTA_KERNEL_ERROR
        )

        with pytest.raises(TransientObjectStoreError):
            DataWarehouseTable()._safe_expose_ch_error(delta_kernel_error)


class TestRunChdbQuery:
    def test_hung_query_is_killed_and_raises_instead_of_blocking(self) -> None:
        # Real subprocess: chdb import alone exceeds the timeout, so this exercises the
        # actual kill path. Guards the regression where a stalled chdb S3 read wedged web
        # workers indefinitely (no timeout around the embedded query).
        with pytest.raises(RuntimeError, match="timed out"):
            run_chdb_query("SELECT sleep(2)", timeout=0.5)

    def test_suppressed_delta_error_classification_survives_subprocess_boundary(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="Code: 36. DB::Exception: Unsupported DeltaLake type: timestamp_ntz. (BAD_ARGUMENTS)",
        )
        with patch("products.warehouse_sources.backend.models.table.subprocess.run", return_value=completed):
            with pytest.raises(RuntimeError) as exc_info:
                run_chdb_query("DESCRIBE TABLE s3('https://example.com/table/')")

        assert DataWarehouseTable()._is_suppressed_chdb_error(exc_info.value)


class TestGetHogqlFieldForColumn(SimpleTestCase):
    @parameterized.expand(
        [
            # Old-style metadata is just the ClickHouse type string, resolved through a mapping
            # on every query — it must keep its historical String typing so a mapping change
            # cannot retype every legacy UUID column at once.
            ("old_style_pinned_to_string", "Nullable(UUID)", StringDatabaseField),
            (
                "new_style_stored_type",
                {"clickhouse": "Nullable(UUID)", "hogql": "UUIDDatabaseField"},
                UUIDDatabaseField,
            ),
        ]
    )
    def test_uuid_column_typing(
        self, _name: str, column_definition: dict[str, Any] | str, expected_type: type[DatabaseField]
    ) -> None:
        field = get_hogql_field_for_column("id", column_definition, "UUID", is_nullable=True)

        assert type(field) is expected_type
        assert field.is_nullable()


class TestUrlPatternChangeGuard(BaseTest):
    # A table with no credential is read by ClickHouse under the node's own S3 role, so its
    # url_pattern is only safe to trust because PostHog computed it. This guards that invariant at
    # the model layer so any writer (not just the REST API) is refused by default.
    def _credential_less_table(
        self, url_pattern: str = "https://posthog-owned.example/team_1/x.csv"
    ) -> DataWarehouseTable:
        table = DataWarehouseTable(name="t", format="CSVWithNames", team=self.team, url_pattern=url_pattern)
        table.save(internally_computed_url_pattern=True)
        return table

    def _credentialed_table(self, url_pattern: str = "https://customer-bucket.example/x.csv") -> DataWarehouseTable:
        credential = DataWarehouseCredential.objects.create(
            team=self.team, access_key="access_key", access_secret="access_secret"
        )
        table = DataWarehouseTable(
            name="t", format="CSVWithNames", team=self.team, url_pattern=url_pattern, credential=credential
        )
        table.save()
        return table

    def test_creating_a_credential_less_table_does_not_require_the_flag(self) -> None:
        table = DataWarehouseTable(
            name="t", format="CSVWithNames", team=self.team, url_pattern="https://x.example/a.csv"
        )
        table.save()

        table.refresh_from_db()
        assert table.url_pattern == "https://x.example/a.csv"

    def test_changing_url_pattern_without_the_flag_is_rejected(self) -> None:
        table = self._credential_less_table()

        table.url_pattern = "https://posthog-owned.example/team_2/y.csv"
        with pytest.raises(ValidationError, match="no credential"):
            table.save()

        table.refresh_from_db()
        assert table.url_pattern == "https://posthog-owned.example/team_1/x.csv"

    def test_changing_url_pattern_with_the_flag_is_allowed(self) -> None:
        table = self._credential_less_table()

        table.url_pattern = "https://posthog-owned.example/team_1/y.csv"
        table.save(internally_computed_url_pattern=True)

        table.refresh_from_db()
        assert table.url_pattern == "https://posthog-owned.example/team_1/y.csv"

    def test_changing_url_pattern_on_a_credentialed_table_does_not_require_the_flag(self) -> None:
        table = self._credentialed_table()

        table.url_pattern = "https://customer-bucket.example/renamed.csv"
        table.save()

        table.refresh_from_db()
        assert table.url_pattern == "https://customer-bucket.example/renamed.csv"

    def test_resaving_the_same_url_pattern_does_not_require_the_flag(self) -> None:
        table = self._credential_less_table()

        table.columns = {"id": {"clickhouse": "String", "hogql": "StringDatabaseField", "valid": True}}
        table.save()

        table.refresh_from_db()
        assert table.columns == {"id": {"clickhouse": "String", "hogql": "StringDatabaseField", "valid": True}}

    def test_update_fields_scoped_save_skips_the_check_when_url_pattern_is_excluded(self) -> None:
        # Mirrors ExternalDataSchema._sync_teardown_kind: a save scoped away from url_pattern via
        # update_fields can't have changed it, so the extra DB read to compare prior state is skipped.
        table = self._credential_less_table()

        table.url_pattern = "https://posthog-owned.example/team_2/y.csv"  # not persisted below
        table.columns = {"id": {"clickhouse": "String", "hogql": "StringDatabaseField", "valid": True}}
        table.save(update_fields=["columns"])

        table.refresh_from_db()
        assert table.url_pattern == "https://posthog-owned.example/team_1/x.csv"
        assert table.columns == {"id": {"clickhouse": "String", "hogql": "StringDatabaseField", "valid": True}}

    def test_attaching_a_credential_in_the_same_call_still_requires_the_flag(self) -> None:
        # The guard reads the row's prior DB state, not the value being assigned in this call, so
        # attaching a real credential here doesn't retroactively make the prior state trusted -
        # writers computing url_pattern from something other than request input (like the demo and
        # seed-data table registration) still have to declare that explicitly.
        table = self._credential_less_table()
        credential = DataWarehouseCredential.objects.create(
            team=self.team, access_key="access_key", access_secret="access_secret"
        )

        table.credential = credential
        table.url_pattern = "https://posthog-owned.example/team_1/y.csv"
        with pytest.raises(ValidationError, match="no credential"):
            table.save()

        table.refresh_from_db()
        assert table.url_pattern == "https://posthog-owned.example/team_1/x.csv"

    def test_full_clean_rejects_the_same_way_save_does(self) -> None:
        # Django admin validates via full_clean() (form.is_valid() -> clean()) before ever calling
        # save(), and ModelAdmin.save_model() doesn't translate a save()-raised ValidationError into
        # a form error - so the same check has to be reachable from clean() too, for admin to show a
        # normal field error instead of an unhandled 500.
        table = self._credential_less_table()

        table.url_pattern = "https://posthog-owned.example/team_2/y.csv"
        with pytest.raises(ValidationError, match="no credential"):
            table.full_clean()

    def test_clean_allows_a_credentialed_table_to_change_url_pattern(self) -> None:
        # Calls clean() directly rather than full_clean(): other required fields (row_count,
        # size_in_s3_mib) are legitimately blank on a freshly built table and full_clean() would
        # reject those regardless, which isn't what this test is checking.
        table = self._credentialed_table()

        table.url_pattern = "https://customer-bucket.example/renamed.csv"
        table.clean()  # must not raise

    def test_soft_delete_on_a_credential_less_table_does_not_trip_the_guard(self) -> None:
        table = self._credential_less_table()

        table.soft_delete()

        table.refresh_from_db()
        assert table.deleted is True
