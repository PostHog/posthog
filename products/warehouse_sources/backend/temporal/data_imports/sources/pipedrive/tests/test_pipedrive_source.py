import datetime

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pipedrive import (
    PipedriveSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.source import PipedriveSource


class TestPipedriveSource:
    def setup_method(self) -> None:
        self.source = PipedriveSource()
        self.team_id = 123
        self.config = PipedriveSourceConfig(company_domain="acme", api_token="token")

    def test_v1_is_deprecated_with_vendor_sunset_and_default_is_v2(self) -> None:
        # New sources start on v2; v1 stays supported but carries the vendor's sunset date so the
        # generic in-product deprecation warning fires.
        assert self.source.default_version == "v2"
        assert set(self.source.supported_versions) == {"v1", "v2"}

        deprecation = self.source.get_version_deprecation("v1")
        assert deprecation is not None
        assert deprecation.sunset_at == datetime.date(2025, 12, 31)
        assert self.source.get_version_deprecation("v2") is None

    @pytest.mark.parametrize(
        "status, schema_name, expected_valid, expected_message",
        [
            (200, None, True, None),
            (200, "deals", True, None),
            (403, None, True, None),
            (403, "deals", False, "Invalid Pipedrive API token or insufficient permissions"),
            (401, None, False, "Invalid Pipedrive API token or insufficient permissions"),
            (500, None, False, "Could not validate Pipedrive credentials"),
            (None, None, False, "Could not validate Pipedrive credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.source.validate_pipedrive_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        status: int | None,
        schema_name: str | None,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = status

        is_valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name)

        assert is_valid is expected_valid
        assert message == expected_message
        mock_validate.assert_called_once_with("acme", "token")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.source.validate_pipedrive_credentials"
    )
    def test_validate_credentials_rejects_invalid_domain(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.side_effect = ValueError("Invalid Pipedrive company domain: 'evil.com'")
        is_valid, message = self.source.validate_credentials(
            PipedriveSourceConfig(company_domain="evil.com", api_token="token"), self.team_id
        )
        assert is_valid is False
        assert message is not None and "Invalid Pipedrive company domain" in message

    def test_webhook_template_verifies_basic_auth_credentials(self) -> None:
        template = self.source.webhook_template

        assert template is not None
        assert template.type == "warehouse_source_webhook"
        input_keys = {item["key"] for item in template.inputs_schema}
        assert {"http_auth_user", "http_auth_password"} <= input_keys

    @pytest.mark.parametrize(
        "method_name, patched",
        [
            ("create_webhook", "create_pipedrive_webhook"),
            ("delete_webhook", "delete_pipedrive_webhook"),
            ("get_external_webhook_info", "get_pipedrive_webhook_info"),
        ],
    )
    def test_webhook_management_passes_domain_then_token(self, method_name: str, patched: str) -> None:
        with mock.patch(
            f"products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.source.{patched}"
        ) as mocked:
            getattr(self.source, method_name)(self.config, "https://webhooks.example/hook", self.team_id)

        mocked.assert_called_once_with("acme", "token", "https://webhooks.example/hook")
