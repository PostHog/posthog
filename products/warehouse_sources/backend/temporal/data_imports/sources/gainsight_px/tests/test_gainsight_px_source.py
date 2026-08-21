import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.source import GainsightPxSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gainsightpx import (
    GainsightPxSourceConfig,
)


class TestGainsightPxSource:
    def setup_method(self):
        self.source = GainsightPxSource()
        self.team_id = 123
        self.config = GainsightPxSourceConfig(api_key="key", region="us")

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_every_endpoint_advertises_a_primary_key(self, endpoint):
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        assert schema.detected_primary_keys

    @pytest.mark.parametrize(
        "mock_return, expected_valid",
        [(True, True), (False, False)],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.source.validate_gainsight_px_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert (error_message is None) is expected_valid
        mock_validate.assert_called_once_with(self.config.api_key, self.config.region)
