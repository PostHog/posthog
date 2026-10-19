import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.doppler.source import DopplerSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.doppler import (
    DopplerSourceConfig,
)


class TestDopplerSource:
    def setup_method(self):
        self.source = DopplerSource()
        self.team_id = 123
        self.config = DopplerSourceConfig(api_token="dp.pt.token")

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["activity_logs"])
        assert [schema.name for schema in schemas] == ["activity_logs"]
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Doppler API token"),
            ((False, 403), False, "Could not connect to Doppler with the provided API token"),
            ((False, None), False, "Could not connect to Doppler with the provided API token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.doppler.source.validate_doppler_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("dp.pt.token")
