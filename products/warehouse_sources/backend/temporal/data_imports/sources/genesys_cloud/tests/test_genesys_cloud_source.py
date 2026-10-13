from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.genesyscloud import (
    GenesysCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.genesys_cloud.genesys_cloud import (
    InvalidGenesysCloudRegionError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.genesys_cloud.source import GenesysCloudSource


class TestGenesysCloudSource:
    def setup_method(self):
        self.source = GenesysCloudSource()

    def test_validate_credentials_rejects_unknown_table(self):
        config = GenesysCloudSourceConfig(region="mypurecloud.com", client_id="cid", client_secret="secret")

        with scripted_network([]) as network:
            result = self.source.validate_credentials(config, team_id=1, schema_name="recordings")

        assert result == (False, "Genesys Cloud has no table named recordings.")
        assert network.requests_log == []

    def test_unknown_region_fails_before_any_request(self):
        config = GenesysCloudSourceConfig(
            region="evil.example.com",  # type: ignore[arg-type]
            client_id="cid",
            client_secret="secret",
        )

        result = SourceDriver(self.source, config).run("conversations", [])

        assert isinstance(result.raised, InvalidGenesysCloudRegionError)
        assert result.requests == []
