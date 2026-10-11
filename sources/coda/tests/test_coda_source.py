import pytest
from unittest import mock

from sources.coda._config import CodaSourceConfig
from sources.coda.source import CodaSource


class TestCodaSource:
    def setup_method(self):
        self.source = CodaSource()
        self.team_id = 123
        self.config = CodaSourceConfig(api_token="api-token")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Coda API token"),
        ],
    )
    @mock.patch("sources.coda.source.validate_coda_credentials")
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_token)
