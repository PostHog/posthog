from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rss import RssSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.rss.source import RssSource


class TestRssSource:
    def setup_method(self) -> None:
        self.source = RssSource()
        self.team_id = 123
        self.config = RssSourceConfig(api_key="rss-key")

    @parameterized.expand(
        [
            (
                "payment_required",
                "402 Client Error: Payment Required for url: https://api.rss.com/v4/podcasts",
            ),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.rss.source.validate_credentials")
    def test_validate_credentials_delegates_with_api_key(self, mock_validate: mock.MagicMock) -> None:
        # The status-to-message mapping lives in rss.validate_credentials; here we only assert the
        # source probes with the configured key and returns the delegate's verdict unchanged.
        mock_validate.return_value = (False, "Invalid RSS.com API key")
        result = self.source.validate_credentials(self.config, self.team_id)
        mock_validate.assert_called_once_with("rss-key")
        assert result == (False, "Invalid RSS.com API key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.rss.source.rss_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "episodes"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "rss-key"
        assert kwargs["endpoint"] == "episodes"
        assert kwargs["resumable_source_manager"] is manager
