import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.bitrise.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.bitrise.source import BitriseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bitrise import (
    BitriseSourceConfig,
)


class TestBitriseSource:
    def setup_method(self):
        self.source = BitriseSource()
        self.team_id = 123
        self.config = BitriseSourceConfig(api_token="bitrise-token")

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only builds (and artifacts, through their parent build fan-out) can be filtered
        # server-side via the `after` Unix-timestamp param.
        assert incremental == {"builds", "artifacts"}

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Bitrise API token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.bitrise.source.validate_bitrise_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_token)
