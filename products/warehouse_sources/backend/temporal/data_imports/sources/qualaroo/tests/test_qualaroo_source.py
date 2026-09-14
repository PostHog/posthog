import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.qualaroo import (
    QualarooSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qualaroo.source import QualarooSource


class TestQualarooSource:
    def setup_method(self) -> None:
        self.source = QualarooSource()
        self.team_id = 123
        self.config = QualarooSourceConfig(api_key="q-key", api_secret="q-secret")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Qualaroo"
        assert config.label == "Qualaroo"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible — it must not carry the scaffolding flag.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/qualaroo"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key", "api_secret"]

    def test_no_connection_host_fields(self) -> None:
        # Both fields are secret credentials; the base URL is hardcoded, so there is no non-secret
        # field an editor could retarget to reuse a preserved secret against another account.
        assert self.source.connection_host_fields == []

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.qualaroo.com/api/v1/nudges.json?limit=500&offset=0",),
            ("403 Client Error: Forbidden for url: https://api.qualaroo.com/api/v1/nudges.json?limit=500&offset=0",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://api.qualaroo.com/api/v1/nudges.json",),
            ("429 Client Error: Too Many Requests for url: https://api.qualaroo.com/api/v1/nudges.json",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.qualaroo.source._validate_qualaroo_credentials"
    )
    def test_validate_credentials_delegates_to_qualaroo(self, mock_validate: mock.MagicMock) -> None:
        # The status-to-result mapping lives in qualaroo.validate_credentials; the source only forwards
        # the account-wide key/secret and returns the result unchanged.
        mock_validate.return_value = (False, "Invalid Qualaroo API key or secret")
        result = self.source.validate_credentials(self.config, self.team_id)
        mock_validate.assert_called_once_with("q-key", "q-secret")
        assert result == (False, "Invalid Qualaroo API key or secret")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.qualaroo.source.qualaroo_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "nudges"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "q-key"
        assert kwargs["api_secret"] == "q-secret"
        assert kwargs["endpoint"] == "nudges"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Qualaroo schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
