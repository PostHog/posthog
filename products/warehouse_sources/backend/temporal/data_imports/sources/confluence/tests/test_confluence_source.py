from products.warehouse_sources.backend.temporal.data_imports.sources.confluence.source import ConfluenceSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.confluence import (
    ConfluenceSourceConfig,
)


class TestConfluenceSource:
    def setup_method(self) -> None:
        self.source = ConfluenceSource()
        self.team_id = 123
        self.config = ConfluenceSourceConfig(subdomain="acme", email="you@example.com", api_token="token")

    def test_connection_host_fields_includes_subdomain(self) -> None:
        # Changing the subdomain retargets where the API token is sent.
        assert self.source.connection_host_fields == ["subdomain"]
