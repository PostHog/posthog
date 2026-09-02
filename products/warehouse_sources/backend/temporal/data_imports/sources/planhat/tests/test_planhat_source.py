import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.planhat import (
    PlanhatSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.planhat.source import PlanhatSource


class TestPlanhatSource:
    def setup_method(self) -> None:
        self.source = PlanhatSource()
        self.team_id = 123
        self.config = PlanhatSourceConfig(api_key="ph-token")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Planhat"
        assert config.label == "Planhat"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible — it must not carry the scaffolding flag.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/planhat"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_no_connection_host_fields(self) -> None:
        # The only field is the secret API token; the base URL is hardcoded, so there is no non-secret
        # field an editor could retarget to reuse a preserved token against another account.
        assert self.source.connection_host_fields == []

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.planhat.com/companies?limit=100&offset=0",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.planhat.com/endusers?limit=100&offset=0"),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.planhat.com/companies"),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.planhat.com/endusers"),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.planhat.source.validate_credentials")
    def test_validate_credentials_delegates_to_planhat(self, mock_validate: mock.MagicMock) -> None:
        # source.py owns no mapping logic — it forwards the account-wide token and returns the result verbatim.
        mock_validate.return_value = (False, "Invalid Planhat API token")
        result = self.source.validate_credentials(self.config, self.team_id)
        mock_validate.assert_called_once_with("ph-token")
        assert result == (False, "Invalid Planhat API token")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.planhat.source.planhat_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "companies"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_token"] == "ph-token"
        assert kwargs["endpoint"] == "companies"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Planhat schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
