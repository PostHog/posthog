from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.klaus import KlausSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.klaus.source import KlausSource


class TestKlausSource:
    def setup_method(self) -> None:
        self.source = KlausSource()
        self.team_id = 123
        self.config = KlausSourceConfig(subdomain="acme", api_token="test-token")

    def test_subdomain_is_a_connection_host_field(self) -> None:
        # Changing the subdomain retargets where the stored token is sent, so it must
        # force the token to be re-entered.
        assert self.source.connection_host_fields == ["subdomain"]

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["reviews", "nonexistent"])
        assert [s.name for s in schemas] == ["reviews"]
