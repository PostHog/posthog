import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.campayn.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.campayn.source import CampaynSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.campayn import (
    CampaynSourceConfig,
)


class TestCampaynSource:
    def setup_method(self) -> None:
        self.source = CampaynSource()
        self.team_id = 123
        self.config = CampaynSourceConfig(subdomain="acme", api_key="campayn-key")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Campayn"
        assert config.label == "Campayn"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible to users — the scaffold's unreleasedSource flag must be gone.
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/campayn.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/campayn"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["subdomain", "api_key"]

    def test_subdomain_is_a_connection_host_field(self) -> None:
        # Changing the subdomain retargets where the API key is sent, so it must re-require the secret.
        assert self.source.connection_host_fields == ["subdomain"]

    def test_documented_tables_render_for_public_docs(self) -> None:
        # lists_tables_without_credentials=True + static get_schemas means the doc's Supported tables
        # section is populated without a live connection.
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://acme.campayn.com/api/v1/lists.json",
            "403 Client Error: Forbidden for url: https://acme.campayn.com/api/v1/emails.json",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

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
