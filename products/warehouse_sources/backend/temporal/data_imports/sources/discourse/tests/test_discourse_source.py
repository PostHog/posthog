import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.discourse.source import DiscourseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.discourse import (
    DiscourseSourceConfig,
)


class TestDiscourseSource:
    def setup_method(self) -> None:
        self.source = DiscourseSource()
        self.team_id = 123
        self.config = DiscourseSourceConfig(
            base_url="https://forum.example.com", api_key="secret-key", api_username="system"
        )

    def test_config_has_no_unreleased_flag(self) -> None:
        # A finished source must not carry `unreleasedSource` — it hides the connector entirely.
        assert self.source.get_source_config.unreleasedSource is None

    def test_connection_host_fields_covers_base_url_and_api_username(self) -> None:
        # The stored API key is sent to whatever `base_url` points at, and `api_username` selects
        # the identity an All Users key acts as, so retargeting either must force key re-entry.
        assert self.source.connection_host_fields == ["base_url", "api_username"]

    @parameterized.expand(
        [
            ("403 Client Error: Forbidden for url: https://forum.example.com/session/current.json",),
            ("invalid_access",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://forum.example.com/latest.json",),
            ("429 Client Error: Too Many Requests for url: https://forum.example.com/posts.json",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.discourse.source.discourse_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "posts"
        inputs.team_id = self.team_id
        inputs.job_id = "job-123"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 42
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["base_url"] == "https://forum.example.com"
        assert kwargs["api_key"] == "secret-key"
        assert kwargs["api_username"] == "system"
        assert kwargs["endpoint"] == "posts"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["job_id"] == "job-123"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 42

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "nope"
        with pytest.raises(ValueError, match="Unknown Discourse schema"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
