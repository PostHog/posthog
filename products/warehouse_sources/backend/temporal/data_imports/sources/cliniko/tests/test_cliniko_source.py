import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.cliniko.source import ClinikoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cliniko import (
    ClinikoSourceConfig,
)


class TestClinikoSource:
    def setup_method(self) -> None:
        self.source = ClinikoSource()
        self.team_id = 123
        self.config = ClinikoSourceConfig(api_key="test-key-au1")

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid", "expected_message"),
        [
            (True, True, None),
            (False, False, "Invalid credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.cliniko.source.validate_cliniko_credentials"
    )
    def test_validate_credentials(
        self, mock_validate: mock.MagicMock, mock_return: bool, expected_valid: bool, expected_message: str | None
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("test-key-au1")
