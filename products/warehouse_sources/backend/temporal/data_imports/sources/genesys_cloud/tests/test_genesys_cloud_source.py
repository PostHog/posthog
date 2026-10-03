import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAuth2AuthRequestError,
)
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

    @pytest.mark.parametrize(
        "observed_error",
        [
            str(OAuth2AuthRequestError("HTTP 401 from the OAuth2 token endpoint: invalid_client", is_permanent=True)),
            "403 Client Error: Forbidden for url: https://api.mypurecloud.com/api/v2/analytics/conversations/details/query",
            str(InvalidGenesysCloudRegionError("Unknown Genesys Cloud region: 'evil.example.com'")),
        ],
    )
    def test_permanent_failures_are_non_retryable(self, observed_error):
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "observed_error",
        [
            str(OAuth2AuthRequestError("HTTP 503 from the OAuth2 token endpoint", is_permanent=False)),
            "429 Client Error: Too Many Requests for url: https://api.mypurecloud.com/api/v2/routing/queues",
        ],
    )
    def test_transient_failures_are_retryable(self, observed_error):
        assert not any(key in observed_error for key in self.source.get_non_retryable_errors())

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
