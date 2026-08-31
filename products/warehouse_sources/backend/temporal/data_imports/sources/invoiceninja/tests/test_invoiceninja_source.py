from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.invoiceninja import (
    InvoiceninjaSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.invoiceninja.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.invoiceninja.source import InvoiceninjaSource


class TestInvoiceninjaSource:
    def setup_method(self):
        self.source = InvoiceninjaSource()
        self.team_id = 123
        self.config = InvoiceninjaSourceConfig(api_token="tok", base_url=None)

    def test_connection_host_fields_force_secret_reentry(self):
        # The API token is sent to base_url, so retargeting it must re-require the token.
        assert self.source.connection_host_fields == ["base_url"]

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_all_schemas_are_full_refresh(self):
        # Incremental is deferred until the server-side filter + sort order are verified against the
        # live API, so every stream ships full-refresh only.
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["invoices"])
        assert len(schemas) == 1
        assert schemas[0].name == "invoices"

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
