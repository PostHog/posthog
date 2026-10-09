import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.genesyscloud import (
    GenesysCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.genesys_cloud.genesys_cloud import (
    InvalidGenesysCloudRegionError,
    genesys_cloud_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.genesys_cloud.source import GenesysCloudSource


class TestGenesysCloudSource:
    def setup_method(self):
        self.source = GenesysCloudSource()

    def test_validate_credentials_rejects_unknown_table(self):
        config = GenesysCloudSourceConfig(region="mypurecloud.com", client_id="cid", client_secret="secret")

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.genesys_cloud.source.validate_genesys_cloud_credentials"
        ) as validate:
            result = self.source.validate_credentials(config, team_id=1, schema_name="recordings")

        assert result == (False, "Genesys Cloud has no table named recordings.")
        validate.assert_not_called()

    def test_unknown_region_fails_before_any_request(self):
        with pytest.raises(InvalidGenesysCloudRegionError):
            genesys_cloud_source(
                region="evil.example.com",
                client_id="cid",
                client_secret="secret",
                endpoint="conversations",
                resumable_source_manager=mock.MagicMock(),
            )
