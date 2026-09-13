import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.huntr import HuntrSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.huntr.source import HuntrSource


class TestHuntrSource:
    def setup_method(self) -> None:
        self.source = HuntrSource()
        self.team_id = 123
        self.config = HuntrSourceConfig(access_token="huntr-token")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Huntr"
        assert config.label == "Huntr"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible — it must not carry the scaffolding flag.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/huntr"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["access_token"]

    def test_no_connection_host_fields(self) -> None:
        # The only field is the secret access token; the base URL is hardcoded, so there is no
        # non-secret field an editor could retarget to reuse a preserved token against another account.
        assert self.source.connection_host_fields == []

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.huntr.co/org/members?limit=100",
            "403 Client Error: Forbidden for url: https://api.huntr.co/org/jobs?limit=100",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @pytest.mark.parametrize(
        "unrelated_error",
        [
            "500 Server Error: Internal Server Error for url: https://api.huntr.co/org/members",
            "429 Client Error: Too Many Requests for url: https://api.huntr.co/org/jobs",
        ],
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.huntr.source.huntr_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "jobs"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["access_token"] == "huntr-token"
        assert kwargs["endpoint"] == "jobs"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Huntr schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
