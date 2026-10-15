import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.sources.clerk.clerk import _webhook_table_transformer
from products.warehouse_sources.backend.temporal.data_imports.sources.clerk.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.clerk.source import ClerkSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clerk import ClerkSourceConfig


class TestClerkSource:
    def setup_method(self):
        self.source = ClerkSource()
        self.team_id = 123
        self.config = ClerkSourceConfig(secret_key="sk_live_test")

    def test_get_schemas_filtered_by_names(self):
        first_endpoint = next(iter(ENDPOINTS))
        schemas = self.source.get_schemas(self.config, self.team_id, names=[first_endpoint])

        assert len(schemas) == 1
        assert schemas[0].name == first_endpoint

    def test_webhook_transformer_keeps_latest_event_and_skips_deletes(self):
        table = pa.Table.from_pylist(
            [
                {
                    "type": "user.updated",
                    "timestamp": 1767312000000,
                    "data": '{"id":"user_1","email":"new@example.com","created_at":1767225600000}',
                },
                {
                    "type": "user.created",
                    "timestamp": 1767225600000,
                    "data": '{"id":"user_1","email":"old@example.com","created_at":1767225600000}',
                },
                {"type": "user.deleted", "timestamp": 1767398400000, "data": '{"id":"user_1","deleted":true}'},
            ]
        )

        assert _webhook_table_transformer(table).to_pylist() == [
            {"id": "user_1", "email": "new@example.com", "created_at": 1767225600}
        ]
