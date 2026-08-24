from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.tasks.tasks import validate_data_warehouse_table_columns


class TestValidateDataWarehouseTableColumns(APIBaseTest):
    @patch("products.warehouse_sources.backend.tasks.tasks.get_client")
    def test_validate_data_warehouse_table_columns(self, mock_get_client: MagicMock) -> None:
        mock_ph_client = MagicMock()
        mock_get_client.return_value = mock_ph_client

        table = DataWarehouseTable.objects.create(
            name="table_name",
            format="Parquet",
            team=self.team,
            columns={"some_columns": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)"}},
        )

        with patch.object(DataWarehouseTable, "validate_column_type", return_value=True):
            validate_data_warehouse_table_columns(self.team.pk, str(table.id))

        table.refresh_from_db()
        assert table.columns is not None
        some_columns = table.columns.get("some_columns")
        assert some_columns is not None
        valid = some_columns.get("valid")
        assert valid is True
