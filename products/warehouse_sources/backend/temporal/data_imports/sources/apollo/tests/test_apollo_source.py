import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.apollo.source import ApolloSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.apollo import ApolloSourceConfig


class TestApolloSource:
    def setup_method(self):
        self.source = ApolloSource()
        self.team_id = 123
        self.config = ApolloSourceConfig(api_key="api-key")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (
                False,
                False,
                "Apollo rejected this API key. Create a key in Apollo under Settings > Integrations > API. "
                "API access requires a paid Apollo plan.",
            ),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.apollo.source.validate_apollo_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key)
