from unittest.mock import MagicMock, patch

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

    def _database(self, field: FieldOrTable, *, denied: bool = False) -> MagicMock:
        database = MagicMock(spec=Database)
        database.has_table.return_value = True
        database.is_table_access_denied.return_value = denied
        database.get_table.return_value = Table(fields={"created_at": field})
        return database

    @parameterized.expand(
        [
            ("datetime", DateTimeDatabaseField(name="created_at")),
            # Curated sources expose converted datetimes as computed columns.
            ("computed", ExpressionField(name="created_at", expr=ast.Call(name="toDateTime", args=[]))),
        ]
    )
    def test_accepts_date_like_columns(self, _name: str, field: FieldOrTable) -> None:
        with patch.object(Database, "create_for", return_value=self._database(field)):
            enforce_warehouse_metric_timestamp_types([self._metric()], team=MagicMock())

    def test_rejects_plain_string_column(self) -> None:
        with (
            patch.object(Database, "create_for", return_value=self._database(StringDatabaseField(name="created_at"))),
            self.assertRaisesMessage(
                ValidationError, "Column 'created_at' on data warehouse table 'payments' has type string"
            ),
        ):
            enforce_warehouse_metric_timestamp_types([self._metric()], team=MagicMock())

    def test_rechecks_a_cached_rejection_against_fresh_sources(self) -> None:
        # A column converted to a datetime within the sources cache TTL must not be rejected on the stale type.
        stale = self._database(StringDatabaseField(name="created_at"))
        fresh = self._database(DateTimeDatabaseField(name="created_at"))
        with patch.object(Database, "create_for", side_effect=[stale, fresh]) as create_for:
            enforce_warehouse_metric_timestamp_types([self._metric()], team=MagicMock())
        assert [call.kwargs["use_cached_sources"] for call in create_for.call_args_list] == [True, False]

    def test_skips_table_the_caller_is_denied(self) -> None:
        # The query must fail on access later, without this message revealing the column's type.
        database = self._database(StringDatabaseField(name="created_at"), denied=True)
        with patch.object(Database, "create_for", return_value=database):
            enforce_warehouse_metric_timestamp_types([self._metric()], team=MagicMock(), user=MagicMock())
        database.get_table.assert_not_called()
