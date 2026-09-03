import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.secoda import SecodaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.secoda.source import SecodaSource


class TestSecodaSource:
    def setup_method(self) -> None:
        self.source = SecodaSource()
        self.team_id = 123
        self.config = SecodaSourceConfig(api_key="sk-key")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Secoda"
        assert config.label == "Secoda"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible — it must not carry the scaffolding flag.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/secoda"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_no_connection_host_fields(self) -> None:
        # The only field is the secret API key; the base URL is hardcoded, so there is no non-secret
        # field an editor could retarget to reuse a preserved key against another account.
        assert self.source.connection_host_fields == []

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.secoda.co/api/v1/table/tables",),
            ("403 Client Error: Forbidden for url: https://api.secoda.co/api/v1/user",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://api.secoda.co/api/v1/table/tables",),
            ("429 Client Error: Too Many Requests for url: https://api.secoda.co/api/v1/user",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.secoda.source.validate_credentials")
    def test_validate_credentials_delegates_to_shared_helper(self, mock_validate: mock.MagicMock) -> None:
        # The source method forwards the workspace API key to the shared validator and returns its result verbatim.
        mock_validate.return_value = (False, "Invalid Secoda API key")
        result = self.source.validate_credentials(self.config, self.team_id)
        assert result == (False, "Invalid Secoda API key")
        mock_validate.assert_called_once_with("sk-key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.secoda.source.secoda_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "tables"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "sk-key"
        assert kwargs["endpoint"] == "tables"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Secoda schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
