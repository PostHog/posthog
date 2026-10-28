import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.frill.source import FrillSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.frill import FrillSourceConfig


class TestFrillSource:
    def setup_method(self) -> None:
        self.source = FrillSource()
        self.team_id = 123
        self.config = FrillSourceConfig(api_key="test-key")

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid", "expected_message"),
        [
            (True, True, None),
            (False, False, "Invalid Frill API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.frill.source.validate_frill_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        mock_return: bool,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("test-key")
