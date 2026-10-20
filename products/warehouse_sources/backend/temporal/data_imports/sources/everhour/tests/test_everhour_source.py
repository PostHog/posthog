import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.everhour.source import EverhourSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.everhour import (
    EverhourSourceConfig,
)

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.everhour.source"


class TestEverhourSource:
    def setup_method(self) -> None:
        self.source = EverhourSource()
        self.team_id = 123
        self.config = EverhourSourceConfig(api_key="ev_abc")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Everhour API key"),
        ],
    )
    @mock.patch(f"{SOURCE_MODULE}.validate_everhour_credentials")
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
        mock_validate.assert_called_once_with(self.config.api_key)
