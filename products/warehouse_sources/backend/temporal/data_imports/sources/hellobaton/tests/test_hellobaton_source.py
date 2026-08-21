import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hellobaton import (
    HellobatonSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hellobaton.source import HellobatonSource


class TestHellobatonSource:
    def setup_method(self):
        self.source = HellobatonSource()
        self.team_id = 123
        self.config = HellobatonSourceConfig(company="acme", api_key="key")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Baton API key"),
            ((False, 403), False, "Could not connect to Baton with the provided company instance and API key"),
            ((False, None), False, "Could not connect to Baton with the provided company instance and API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.hellobaton.source.validate_hellobaton_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("acme", "key")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.hellobaton.source.validate_hellobaton_credentials"
    )
    def test_validate_credentials_surfaces_bad_company(self, mock_validate):
        mock_validate.side_effect = ValueError("Invalid Baton company: 'a/b'.")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert "Invalid Baton company" in (error_message or "")
