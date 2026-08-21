import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pluralsightflow import (
    PluralsightFlowSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pluralsight_flow.source import (
    PluralsightFlowSource,
)


class TestPluralsightFlowSource:
    def setup_method(self):
        self.source = PluralsightFlowSource()
        self.team_id = 123
        self.config = PluralsightFlowSourceConfig(workspace="acme", api_key="key")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Your Flow API key is invalid or expired."),
            ((False, 403), False, "Invalid credentials"),
            ((False, None), False, "Invalid credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pluralsight_flow.source"
        ".validate_pluralsight_flow_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("key", "acme")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pluralsight_flow.source"
        ".validate_pluralsight_flow_credentials"
    )
    def test_validate_credentials_surfaces_bad_workspace(self, mock_validate):
        mock_validate.side_effect = ValueError("Invalid Flow workspace: 'a/b'.")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert "Invalid Flow workspace" in (error_message or "")
