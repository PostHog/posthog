import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.recruitee import (
    RecruiteeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recruitee.source import RecruiteeSource


class TestRecruiteeSource:
    def setup_method(self) -> None:
        self.source = RecruiteeSource()
        self.team_id = 123
        self.config = RecruiteeSourceConfig(company_id="acme", api_token="rc-token")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Recruitee"
        assert config.label == "Recruitee"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible — it must not carry the scaffolding flag.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/recruitee"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["company_id", "api_token"]

    def test_connection_host_fields_pins_company_id(self) -> None:
        # The secret token is sent to a path derived from company_id, so retargeting the company ID
        # must re-require the token.
        assert self.source.connection_host_fields == ["company_id"]

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.recruitee.com/c/acme/candidates?limit=100&offset=0",),
            ("403 Client Error: Forbidden for url: https://api.recruitee.com/c/acme/offers?limit=100&offset=0",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://api.recruitee.com/c/acme/candidates",),
            ("429 Client Error: Too Many Requests for url: https://api.recruitee.com/c/acme/offers",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.recruitee.source.recruitee_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "candidates"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["company_id"] == "acme"
        assert kwargs["api_token"] == "rc-token"
        assert kwargs["endpoint"] == "candidates"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Recruitee schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
