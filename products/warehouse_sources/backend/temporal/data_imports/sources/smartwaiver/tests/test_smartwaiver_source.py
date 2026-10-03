import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.smartwaiver import (
    SmartwaiverSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartwaiver.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.smartwaiver.source import SmartwaiverSource

# Endpoints exposing Smartwaiver's server-side `fromDts` timestamp filter.
_INCREMENTAL_ENDPOINTS = {"waivers": "createdOn", "checkins": "date"}
_FULL_REFRESH_ENDPOINTS = {"templates"}


class TestSmartwaiverSource:
    def setup_method(self):
        self.source = SmartwaiverSource()
        self.team_id = 123
        self.config = SmartwaiverSourceConfig(api_key="key")

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.smartwaiver.com/v4/waivers?limit=100&offset=0",),
            (
                "403 Client Error: Forbidden for url: https://api.smartwaiver.com/v4/checkins?fromDts=2000-01-01T00%3A00%3A00",
            ),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("429 Client Error: Too Many Requests for url: https://api.smartwaiver.com/v4/waivers",),
            ("500 Server Error: Internal Server Error for url: https://api.smartwaiver.com/v4/waivers",),
            ("HTTPSConnectionPool(host='api.smartwaiver.com', port=443): Read timed out.",),
        ]
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.smartwaiver.source.smartwaiver_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_smartwaiver_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "waivers"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01 00:00:00"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_smartwaiver_source.assert_called_once()
        kwargs = mock_smartwaiver_source.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["endpoint"] == "waivers"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01 00:00:00"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.smartwaiver.source.smartwaiver_source"
    )
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_smartwaiver_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "templates"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01 00:00:00"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_smartwaiver_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self):
        inputs = mock.MagicMock()
        inputs.schema_name = "nope"
        with pytest.raises(ValueError, match="Unknown Smartwaiver schema"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
