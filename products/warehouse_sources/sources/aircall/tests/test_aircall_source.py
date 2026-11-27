import pytest
from unittest import mock

from products.warehouse_sources.sources.aircall._config import AircallSourceConfig
from products.warehouse_sources.sources.aircall.source import AircallSource


class TestAircallSource:
    def setup_method(self):
        self.source = AircallSource()
        self.team_id = 123
        self.config = AircallSourceConfig(api_id="api-id", api_token="api-token")

    @pytest.mark.parametrize(
        "probe_result, expected_valid, expected_substring",
        [
            ((True, 200), True, None),
            ((False, 401), False, "rejected your API ID or API token"),
            ((False, 403), False, "rejected your API ID or API token"),
            ((False, 429), False, "Couldn't reach Aircall"),
            ((False, 500), False, "Couldn't reach Aircall"),
            ((False, None), False, "Couldn't reach Aircall"),
        ],
    )
    @mock.patch("products.warehouse_sources.sources.aircall.source.validate_aircall_credentials")
    def test_validate_credentials(self, mock_validate, probe_result, expected_valid, expected_substring):
        mock_validate.return_value = probe_result

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if expected_substring is None:
            assert error_message is None
        else:
            assert error_message is not None
            assert expected_substring in error_message
        mock_validate.assert_called_once_with(self.config.api_id, self.config.api_token)
