import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.appsignal.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.appsignal.source import AppsignalSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appsignal import (
    AppsignalSourceConfig,
)


class TestAppsignalSource:
    def setup_method(self):
        self.source = AppsignalSource()
        self.team_id = 123
        self.config = AppsignalSourceConfig(api_token="api-token", app_id="app-id")

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only the REST endpoints expose a server-side time filter; the GraphQL incident
        # lists don't, so they stay full refresh.
        assert incremental == {"deploy_markers", "error_samples", "performance_samples"}

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid AppSignal personal API token or app ID"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.appsignal.source.validate_appsignal_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_token, self.config.app_id)
