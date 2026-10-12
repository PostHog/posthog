import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.humanitix import (
    HumanitixSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.humanitix.source import HumanitixSource


class TestHumanitixSource:
    def setup_method(self) -> None:
        self.source = HumanitixSource()
        self.team_id = 123
        self.config = HumanitixSourceConfig(api_key="hmtx-key")

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.humanitix.com/v1/events?page=1&pageSize=100",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.humanitix.com/v1/tags?page=2&pageSize=100"),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.humanitix.com/v1/events"),
            ("read_timeout", "HTTPSConnectionPool(host='api.humanitix.com', port=443): Read timed out."),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.humanitix.com/v1/tags"),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.humanitix.source.validate_humanitix_credentials"
    )
    def test_validate_credentials_probes_the_account_key(self, mock_validate: mock.MagicMock) -> None:
        # The API key is account-wide, so validation probes the key, not a per-schema scope.
        mock_validate.return_value = (200, None)
        self.source.validate_credentials(self.config, self.team_id, schema_name="tags")
        mock_validate.assert_called_once_with("hmtx-key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.humanitix.source.humanitix_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_humanitix_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "events"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_humanitix_source.assert_called_once()
        kwargs = mock_humanitix_source.call_args.kwargs
        assert kwargs["api_key"] == "hmtx-key"
        assert kwargs["endpoint"] == "events"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Humanitix schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
