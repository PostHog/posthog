import subprocess
from typing import Any

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from clickhouse_driver.errors import ServerException
from parameterized import parameterized

from posthog.hogql.database.models import DatabaseField, StringDatabaseField, UUIDDatabaseField

from posthog.exceptions import ClickHouseAtCapacity

from products.warehouse_sources.backend.models.table import (
    DataWarehouseTable,
    get_hogql_field_for_column,
    run_chdb_query,
)


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
    # It must be re-raised as-is — not crash on the missing attribute, nor be masked as a
    # storage-bucket misconfiguration, which would hide a retryable error from Temporal.
    @pytest.mark.parametrize(
        "err",
        [EOFError("Unexpected EOF while reading bytes"), ConnectionResetError("Connection reset by peer")],
    )
    def test_transient_errors_without_message_are_reraised_untouched(self, err: Exception) -> None:
        with pytest.raises(type(err)) as exc_info:
            DataWarehouseTable()._safe_expose_ch_error(err)
        assert exc_info.value is err


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
