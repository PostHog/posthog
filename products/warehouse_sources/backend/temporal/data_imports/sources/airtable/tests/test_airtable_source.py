import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.airtable.source import AirtableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.airtable import (
    AirtableSourceConfig,
)


class TestAirtableSource:
    def setup_method(self):
        self.source = AirtableSource()
        self.team_id = 123
        self.config = AirtableSourceConfig(personal_access_token="pat-token")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (
                False,
                False,
                "Invalid Airtable personal access token. Check that the token is correct and has access to the bases you want to sync, then try again.",
            ),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.airtable.source.validate_airtable_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.personal_access_token)
