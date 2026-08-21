import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.env0.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.env0.source import Env0Source
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.env0 import Env0SourceConfig


class TestEnv0Source:
    def setup_method(self):
        self.source = Env0Source()
        self.team_id = 123
        self.config = Env0SourceConfig(api_key_id="key-id", api_key_secret="key-secret")

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only deployments expose env0's server-side fromDate/toDate window.
        assert incremental == {"deployments"}

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid env0 API key credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.env0.source.validate_env0_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key_id, self.config.api_key_secret)
