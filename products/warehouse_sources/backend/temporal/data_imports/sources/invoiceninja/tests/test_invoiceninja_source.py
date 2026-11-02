from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.invoiceninja import (
    InvoiceninjaSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.invoiceninja.source import InvoiceninjaSource


class TestInvoiceninjaSource:
    def setup_method(self):
        self.source = InvoiceninjaSource()
        self.team_id = 123
        self.config = InvoiceninjaSourceConfig(api_token="tok", base_url=None)

    def test_connection_host_fields_force_secret_reentry(self):
        # The API token is sent to base_url, so retargeting it must re-require the token.
        assert self.source.connection_host_fields == ["base_url"]
