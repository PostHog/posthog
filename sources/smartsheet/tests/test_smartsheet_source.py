import pytest
from unittest import mock

from sources.smartsheet._config import SmartsheetSourceConfig
from sources.smartsheet.source import SmartsheetSource


class TestSmartsheetSource:
    def setup_method(self):
        self.source = SmartsheetSource()
        self.team_id = 123
        self.config = SmartsheetSourceConfig(access_token="token")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Smartsheet access token"),
        ],
    )
    @mock.patch("sources.smartsheet.source.validate_smartsheet_credentials")
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.access_token)
