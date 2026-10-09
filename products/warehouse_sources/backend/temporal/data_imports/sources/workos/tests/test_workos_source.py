import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.workos import WorkOSSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.workos.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.workos.source import WorkOSSource
from products.warehouse_sources.backend.temporal.data_imports.sources.workos.workos import _webhook_table_transformer


class TestWorkOSSource:
    def setup_method(self):
        self.source = WorkOSSource()
        self.team_id = 123
        self.config = WorkOSSourceConfig(api_key="sk_test_123")

    def test_get_schemas_filtered_by_names(self):
        first_endpoint = next(iter(ENDPOINTS))
        schemas = self.source.get_schemas(self.config, self.team_id, names=[first_endpoint])

        assert len(schemas) == 1
        assert schemas[0].name == first_endpoint

    def test_webhook_transformer_extracts_rows_and_marks_deletes(self):
        table = pa.Table.from_pylist(
            [
                {
                    "event": "user.updated",
                    "created_at": "2026-01-01T00:00:00Z",
                    "data": '{"id":"user_1","email":"old@example.com"}',
                },
                {
                    "event": "user.deleted",
                    "created_at": "2026-01-02T00:00:00Z",
                    "data": '{"id":"user_1","email":"old@example.com"}',
                },
            ]
        )

        assert _webhook_table_transformer(table).to_pylist() == [
            {
                "id": "user_1",
                "email": "old@example.com",
                "workos_deleted": True,
                "workos_deleted_at": "2026-01-02T00:00:00Z",
            }
        ]
