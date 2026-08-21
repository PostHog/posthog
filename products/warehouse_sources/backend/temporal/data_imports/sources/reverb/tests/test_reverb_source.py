import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.reverb import ReverbSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.reverb.source import ReverbSource

_INCREMENTAL_ENDPOINTS = {"Orders", "Payouts"}
_FULL_REFRESH_ENDPOINTS = {"Listings"}


class TestReverbSource:
    def setup_method(self):
        self.source = ReverbSource()
        self.team_id = 123
        self.config = ReverbSourceConfig(api_token="token")

    def test_supported_api_version_is_declared_and_not_deprecated(self):
        assert self.source.default_version in self.source.supported_versions
        assert self.source.get_version_deprecation(self.source.default_version) is None

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Reverb personal access token"),
            ((False, 403), False, "Could not connect to Reverb with the provided personal access token"),
            ((False, None), False, "Could not connect to Reverb with the provided personal access token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.reverb.source.validate_reverb_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("token", "3.0")
