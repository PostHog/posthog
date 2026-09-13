import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ruddr import RuddrSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.ruddr.source import RuddrSource


class TestRuddrSource:
    def setup_method(self) -> None:
        self.source = RuddrSource()
        self.team_id = 123
        self.config = RuddrSourceConfig(api_key="ruddr-key")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Ruddr"
        assert config.label == "Ruddr"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible — it must not carry the scaffolding flag.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/ruddr"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_no_connection_host_fields(self) -> None:
        # The only field is the secret API key; the base URL is hardcoded, so there is no non-secret
        # field an editor could retarget to reuse a preserved key against another workspace.
        assert self.source.connection_host_fields == []

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://www.ruddr.io/api/workspace/clients?limit=100",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://www.ruddr.io/api/workspace/projects?limit=100"),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://www.ruddr.io/api/workspace/clients",
            ),
            (
                "rate_limited",
                "429 Client Error: Too Many Requests for url: https://www.ruddr.io/api/workspace/projects",
            ),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.ruddr.source.validate_credentials")
    def test_validate_credentials_delegates_with_api_key(self, mock_validate: mock.MagicMock) -> None:
        # The status-to-message mapping lives in ruddr.validate_credentials; here we only assert the
        # source probes with the configured key and returns the delegate's verdict unchanged.
        mock_validate.return_value = (False, "Invalid Ruddr API key")
        result = self.source.validate_credentials(self.config, self.team_id)
        mock_validate.assert_called_once_with("ruddr-key")
        assert result == (False, "Invalid Ruddr API key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.ruddr.source.ruddr_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "clients"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "ruddr-key"
        assert kwargs["endpoint"] == "clients"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Ruddr schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
