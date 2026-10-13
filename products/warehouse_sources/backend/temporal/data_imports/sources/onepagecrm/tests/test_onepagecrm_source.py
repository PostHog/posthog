import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.onepagecrm import (
    OnepagecrmSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onepagecrm.source import OnepagecrmSource


class TestOnepagecrmSource:
    def setup_method(self) -> None:
        self.source = OnepagecrmSource()
        self.team_id = 123
        self.config = OnepagecrmSourceConfig(user_id="uid-1", api_key="key-1")

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://app.onepagecrm.com/api/v3/contacts",),
            ("403 Client Error: Forbidden for url: https://app.onepagecrm.com/api/v3/deals",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://app.onepagecrm.com/api/v3/contacts",),
            ("429 Client Error: Too Many Requests for url: https://app.onepagecrm.com/api/v3/deals",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.onepagecrm.source.onepagecrm_source")
    def test_source_for_pipeline_plumbs_incremental_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "contacts"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["user_id"] == "uid-1"
        assert kwargs["api_key"] == "key-1"
        assert kwargs["endpoint"] == "contacts"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.onepagecrm.source.onepagecrm_source")
    def test_source_for_pipeline_drops_watermark_on_full_refresh(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "contacts"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 1700000000

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown OnePageCRM schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
