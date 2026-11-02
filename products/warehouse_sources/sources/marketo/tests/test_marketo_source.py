from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.marketo import (
    MarketoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.marketo.settings import MARKETO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.marketo.source import MarketoSource

VALIDATE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.marketo.source.validate_marketo_credentials"
)
SOURCE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.marketo.source.marketo_source"

INCREMENTAL_ENDPOINTS = sorted(name for name, c in MARKETO_ENDPOINTS.items() if c.incremental_field)
FULL_REFRESH_ENDPOINTS = sorted(name for name, c in MARKETO_ENDPOINTS.items() if not c.incremental_field)


class TestMarketoSource:
    def setup_method(self) -> None:
        self.source = MarketoSource()
        self.team_id = 123
        self.config = MarketoSourceConfig(
            munchkin_id="123-ABC-456",
            client_id="client-id",
            client_secret="client-secret",
            start_date="2024-01-01",
        )

    def test_api_docs_url_and_public_table_listing(self) -> None:
        assert self.source.api_docs_url is not None
        assert self.source.api_docs_url.startswith("https://")
        # get_schemas iterates a static catalog with no I/O, so the docs can render the tables.
        assert self.source.lists_tables_without_credentials is True
