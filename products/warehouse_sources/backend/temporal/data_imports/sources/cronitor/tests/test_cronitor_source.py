import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.cronitor.source import CronitorSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cronitor import (
    CronitorSourceConfig,
)


class TestCronitorSource:
    def setup_method(self):
        self.source = CronitorSource()
        self.team_id = 123
        self.config = CronitorSourceConfig(api_key="key")

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["metrics"])
        assert len(schemas) == 1
        assert schemas[0].name == "metrics"

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Cronitor API key. Make sure the key has the monitor:read scope."),
            ((False, 403), False, "Invalid Cronitor API key. Make sure the key has the monitor:read scope."),
            ((False, None), False, "Could not connect to Cronitor with the provided API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.cronitor.source.validate_cronitor_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("key")
