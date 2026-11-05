import pytest
from unittest import mock

from products.warehouse_sources.sources.airtable._config import AirtableSourceConfig
from products.warehouse_sources.sources.airtable.source import AirtableSource


class TestAirtableSource:
    def setup_method(self):
        self.source = AirtableSource()
        self.team_id = 123
        self.config = AirtableSourceConfig(personal_access_token="pat-token")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            (
                (False, 401),
                False,
                "Invalid Airtable personal access token. Check that the token is correct and has access to the bases you want to sync, then try again.",
            ),
            (
                (False, None),
                False,
                "Invalid Airtable personal access token. Check that the token is correct and has access to the bases you want to sync, then try again.",
            ),
            (
                (False, 403),
                False,
                "Your Airtable token is missing a required scope. Add the data.records:read and schema.bases:read scopes to the token in Airtable, then try again.",
            ),
        ],
    )
    @mock.patch("products.warehouse_sources.sources.airtable.source.validate_airtable_credentials")
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.personal_access_token)
