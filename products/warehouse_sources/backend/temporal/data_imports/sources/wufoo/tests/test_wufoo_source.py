import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.wufoo import WufooSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.wufoo.source import WufooSource


class TestWufooSource:
    def setup_method(self) -> None:
        self.source = WufooSource()
        self.team_id = 123
        self.config = WufooSourceConfig(subdomain="acme", api_key="wufoo-key")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.label == "Wufoo"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible — it must not carry the scaffolding flag.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/wufoo"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["subdomain", "api_key"]

    def test_field_types(self) -> None:
        fields = {f.name: f for f in self.source.get_source_config.fields if isinstance(f, SourceFieldInputConfig)}
        # The subdomain determines where the key is sent, so it is a plain (non-secret) text field.
        assert fields["subdomain"].type == SourceFieldInputConfigType.TEXT
        assert fields["subdomain"].secret is False
        # The API key is the credential and must be a preserved secret.
        assert fields["api_key"].type == SourceFieldInputConfigType.PASSWORD
        assert fields["api_key"].secret is True

    def test_connection_host_fields_cover_subdomain(self) -> None:
        # The key is sent to <subdomain>.wufoo.com, so editing the subdomain must re-require the key.
        assert self.source.connection_host_fields == ["subdomain"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://acme.wufoo.com/api/v3/forms.json?pageStart=0&pageSize=100",
            "403 Client Error: Forbidden for url: https://acme.wufoo.com/api/v3/reports.json",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @pytest.mark.parametrize(
        "unrelated_error",
        [
            "500 Server Error: Internal Server Error for url: https://acme.wufoo.com/api/v3/forms.json",
            "429 Client Error: Too Many Requests for url: https://acme.wufoo.com/api/v3/users.json",
        ],
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @pytest.mark.parametrize(
        "status, expected_valid",
        [(200, True), (401, False), (403, False), (500, False), (None, False)],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.wufoo.source.validate_wufoo_credentials"
    )
    def test_validate_credentials(
        self, mock_validate: mock.MagicMock, status: int | None, expected_valid: bool
    ) -> None:
        mock_validate.return_value = status
        is_valid, message = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        if expected_valid:
            assert message is None
        else:
            assert message is not None

    def test_validate_credentials_rejects_bad_subdomain_without_probing(self) -> None:
        bad_config = WufooSourceConfig(subdomain="not a domain!", api_key="wufoo-key")
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.wufoo.source.validate_wufoo_credentials"
        ) as mock_validate:
            is_valid, message = self.source.validate_credentials(bad_config, self.team_id)
        assert is_valid is False
        assert message == "Wufoo subdomain is invalid"
        mock_validate.assert_not_called()
