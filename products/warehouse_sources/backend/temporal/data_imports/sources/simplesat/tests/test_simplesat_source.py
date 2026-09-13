import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.simplesat import (
    SimplesatSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.simplesat.source import SimplesatSource


class TestSimplesatSource:
    def setup_method(self) -> None:
        self.source = SimplesatSource()
        self.team_id = 123
        self.config = SimplesatSourceConfig(api_key="ss-key")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Simplesat"
        assert config.label == "Simplesat"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible — it must not carry the scaffolding flag.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/simplesat"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_no_connection_host_fields(self) -> None:
        # The only field is the secret API key; the base URL is hardcoded, so there is no non-secret
        # field an editor could retarget to reuse a preserved key against another account.
        assert self.source.connection_host_fields == []

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.simplesat.io/api/v1/surveys?page_size=100",
            "403 Client Error: Forbidden for url: https://api.simplesat.io/api/v1/questions?page_size=100",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @pytest.mark.parametrize(
        "unrelated_error",
        [
            "500 Server Error: Internal Server Error for url: https://api.simplesat.io/api/v1/surveys",
            "429 Client Error: Too Many Requests for url: https://api.simplesat.io/api/v1/questions",
        ],
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.simplesat.source.validate_credentials"
    )
    def test_validate_credentials_delegates_to_transport(self, mock_validate: mock.MagicMock) -> None:
        # The status → message mapping is covered in test_simplesat.py; here we only lock in that the
        # source passes the api key through and returns the transport helper's verdict unchanged.
        mock_validate.return_value = (False, "Invalid Simplesat API key")
        result = self.source.validate_credentials(self.config, self.team_id)
        mock_validate.assert_called_once_with(self.config.api_key)
        assert result == (False, "Invalid Simplesat API key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.simplesat.source.simplesat_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "surveys"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "ss-key"
        assert kwargs["endpoint"] == "surveys"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Simplesat schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
