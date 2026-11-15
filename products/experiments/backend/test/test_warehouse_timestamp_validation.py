from collections.abc import Collection

from unittest.mock import MagicMock

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.hogql import ast
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    ExpressionField,
    FieldOrTable,
    StringDatabaseField,
    Table,
)

from products.experiments.backend.warehouse_timestamp_validation import enforce_warehouse_metric_timestamp_types


class TestEnforceWarehouseMetricTimestampTypes(SimpleTestCase):
    def _metric(self, table_name: str = "payments", column: str = "created_at") -> dict:
        return {
            "kind": "ExperimentMetric",
            "source": {"kind": "ExperimentDataWarehouseNode", "table_name": table_name, "timestamp_field": column},
        }

    def _database(self, tables: dict[str, FieldOrTable], *, denied: Collection[str] = ()) -> MagicMock:
        database = MagicMock(spec=Database)
        database.has_table.side_effect = lambda name: name in tables
        database.is_table_access_denied.side_effect = lambda name: name in denied
        database.get_table.side_effect = lambda name: Table(fields={"created_at": tables[name]})
        return database

    @parameterized.expand(
        [
            ("datetime", DateTimeDatabaseField(name="created_at")),
            # Curated sources expose converted datetimes as computed columns.
            ("computed", ExpressionField(name="created_at", expr=ast.Call(name="toDateTime", args=[]))),
        ]
    )
    def test_accepts_date_like_columns(self, _name: str, field: FieldOrTable) -> None:
        enforce_warehouse_metric_timestamp_types([self._metric()], self._database({"payments": field}))

    def test_rejects_plain_string_column_on_any_table_in_the_metric(self) -> None:
        database = self._database(
            {"payments": DateTimeDatabaseField(name="created_at"), "refunds": StringDatabaseField(name="created_at")}
        )
        with self.assertRaisesMessage(
            ValidationError, "Column 'created_at' on data warehouse table 'refunds' is not a date or datetime column"
        ):
            enforce_warehouse_metric_timestamp_types([self._metric("payments"), self._metric("refunds")], database)

    def test_skips_table_the_caller_is_denied(self) -> None:
        # The query must fail on access later, as it did before this check existed.
        database = self._database({"payments": StringDatabaseField(name="created_at")}, denied={"payments"})
        enforce_warehouse_metric_timestamp_types([self._metric()], database)
        database.get_table.assert_not_called()
