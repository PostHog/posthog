import subprocess
from typing import Any

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from clickhouse_driver.errors import ServerException
from parameterized import parameterized

from posthog.hogql.database.direct_clickhouse_table import DirectClickHouseTable
from posthog.hogql.database.models import DatabaseField, StringDatabaseField, UUIDDatabaseField
from posthog.hogql.database.s3_table import DataWarehouseTable as HogQLDataWarehouseTable

from posthog.exceptions import ClickHouseAtCapacity

from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import (
    DataWarehouseTable,
    get_hogql_field_for_column,
    run_chdb_query,
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
