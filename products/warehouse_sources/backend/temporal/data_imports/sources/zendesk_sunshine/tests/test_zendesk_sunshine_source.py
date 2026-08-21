import datetime

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zendesksunshine import (
    ZendeskSunshineSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sunshine.settings import (
    ZENDESK_SUNSHINE_V1,
    ZENDESK_SUNSHINE_V2,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sunshine.source import (
    ZendeskSunshineSource,
)


class TestZendeskSunshineSource:
    def setup_method(self) -> None:
        self.source = ZendeskSunshineSource()
        self.team_id = 123
        self.config = ZendeskSunshineSourceConfig(
            subdomain="nibbles", api_key="zendesk-token", email_address="agent@example.com"
        )

    def test_get_schemas_rejects_unsupported_version(self) -> None:
        with pytest.raises(ValueError, match="Unsupported Zendesk Sunshine API version"):
            self.source.get_schemas(self.config, self.team_id, api_version="v9")

    def test_versions_declare_deprecated_v1_with_sunset(self) -> None:
        assert self.source.supported_versions == (ZENDESK_SUNSHINE_V1, ZENDESK_SUNSHINE_V2)
        assert self.source.default_version == ZENDESK_SUNSHINE_V2
        deprecation = self.source.get_version_deprecation(ZENDESK_SUNSHINE_V1)
        assert deprecation is not None
        assert deprecation.sunset_at == datetime.date(2026, 6, 30)
        # The default must never be deprecated — new sources are stamped with it.
        assert self.source.get_version_deprecation(ZENDESK_SUNSHINE_V2) is None

    @pytest.mark.parametrize("bad_subdomain", ["bad domain", "sub.domain!", ""])
    def test_validate_credentials_rejects_invalid_subdomain_without_http(self, bad_subdomain: str) -> None:
        config = ZendeskSunshineSourceConfig(
            subdomain=bad_subdomain, api_key="zendesk-token", email_address="agent@example.com"
        )
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sunshine.source.validate_zendesk_sunshine_credentials"
        ) as mock_validate:
            is_valid, message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert message == "Zendesk subdomain is incorrect"
        mock_validate.assert_not_called()

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sunshine.source.validate_zendesk_sunshine_credentials"
    )
    def test_validate_credentials_plumbs_arguments(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)

        result = self.source.validate_credentials(self.config, self.team_id)

        assert result == (True, None)
        # No pin → resolves to default_version (v2), so a new source validates against v2.
        mock_validate.assert_called_once_with("nibbles", "zendesk-token", "agent@example.com", ZENDESK_SUNSHINE_V2)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sunshine.source.validate_zendesk_sunshine_credentials"
    )
    def test_validate_credentials_plumbs_pinned_version(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)

        self.source.validate_credentials(self.config, self.team_id, api_version=ZENDESK_SUNSHINE_V1)

        mock_validate.assert_called_once_with("nibbles", "zendesk-token", "agent@example.com", ZENDESK_SUNSHINE_V1)
