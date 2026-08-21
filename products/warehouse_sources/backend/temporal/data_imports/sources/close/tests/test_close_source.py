import pytest
from unittest import mock
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.close.source import CloseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.close import CloseSourceConfig

INCREMENTAL_ENDPOINTS = {"Leads", "Contacts", "Opportunities", "Activities", "Tasks"}


class TestCloseSource:
    def setup_method(self) -> None:
        self.source = CloseSource()
        self.team_id = 123
        self.config = CloseSourceConfig(api_key="api_test")

    def test_opportunities_advertises_both_cursors(self) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == "Opportunities")
        fields = {f["field"] for f in schema.incremental_fields}
        assert fields == {"date_created", "date_updated"}

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid", "expected_message"),
        [
            (True, True, None),
            (False, False, "Invalid Close API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.close.source.validate_close_credentials"
    )
    def test_validate_credentials(
        self, mock_validate: MagicMock, mock_return: bool, expected_valid: bool, expected_message: str | None
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("api_test")

    def test_validate_credentials_empty_key(self) -> None:
        is_valid, error_message = self.source.validate_credentials(CloseSourceConfig(api_key=""), self.team_id)
        assert is_valid is False
        assert error_message == "Close API key is required"
