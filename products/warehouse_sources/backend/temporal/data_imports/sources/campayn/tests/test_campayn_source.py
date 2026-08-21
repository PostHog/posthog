import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.campayn.source import CampaynSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.campayn import (
    CampaynSourceConfig,
)


class TestCampaynSource:
    def setup_method(self) -> None:
        self.source = CampaynSource()
        self.team_id = 123
        self.config = CampaynSourceConfig(subdomain="acme", api_key="campayn-key")

    @pytest.mark.parametrize(
        "subdomain, valid_creds, expected_valid, expected_message",
        [
            ("acme", True, True, None),
            ("acme", False, False, "Campayn rejected the credentials. Check the subdomain and API key are correct."),
            ("acme corp", True, False, "Campayn subdomain is incorrect"),
            ("acme@evil.com", True, False, "Campayn subdomain is incorrect"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.campayn.source.validate_campayn_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        subdomain: str,
        valid_creds: bool,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = valid_creds
        config = CampaynSourceConfig(subdomain=subdomain, api_key="k")
        is_valid, message = self.source.validate_credentials(config, self.team_id)
        assert is_valid is expected_valid
        assert message == expected_message

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.campayn.source.validate_campayn_credentials"
    )
    def test_validate_credentials_skips_api_call_for_bad_subdomain(self, mock_validate: mock.MagicMock) -> None:
        config = CampaynSourceConfig(subdomain="acme corp", api_key="k")
        self.source.validate_credentials(config, self.team_id)
        mock_validate.assert_not_called()
