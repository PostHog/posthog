from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.alguna.source import AlgunaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.alguna import AlgunaSourceConfig


class TestAlgunaSource:
    def setup_method(self):
        self.source = AlgunaSource()
        self.team_id = 123
        self.config = AlgunaSourceConfig(api_key="alg-key")

    @parameterized.expand(
        [
            ("valid", True, True, None),
            ("invalid", False, False, "Invalid Alguna API key"),
        ]
    )
    def test_validate_credentials(self, _name, mock_return, expected_valid, expected_message):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.alguna.source.validate_alguna_credentials"
        ) as mock_validate:
            mock_validate.return_value = mock_return

            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

            assert is_valid is expected_valid
            assert error_message == expected_message
            mock_validate.assert_called_once_with(self.config.api_key)
