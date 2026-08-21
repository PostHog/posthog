import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.companycam.source import CompanycamSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.companycam import (
    CompanycamSourceConfig,
)

_INCREMENTAL_ENDPOINTS = {"Projects", "Photos", "Videos"}
_FULL_REFRESH_ENDPOINTS = {"Users", "Tags", "Groups", "Checklists", "ChecklistTemplates"}


class TestCompanycamSource:
    def setup_method(self) -> None:
        self.source = CompanycamSource()
        self.team_id = 123
        self.config = CompanycamSourceConfig(api_key="test-key")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.companycam.source.validate_companycam_credentials"
    )
    def test_validate_credentials(
        self, mock_validate: mock.MagicMock, mock_return: bool, expected_valid: bool, expected_message: str | None
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("test-key", "v2")
