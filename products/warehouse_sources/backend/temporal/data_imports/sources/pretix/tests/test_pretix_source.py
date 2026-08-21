import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pretix import PretixSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pretix.settings import INCREMENTAL_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.pretix.source import PretixSource


class TestPretixSource:
    def setup_method(self):
        self.source = PretixSource()
        self.team_id = 123
        self.config = PretixSourceConfig(organizer="acme", api_token="test-token")

    def test_orders_is_the_only_incremental_endpoint(self):
        # Only `orders` has a documented server-side `modified_since` filter; advertising incremental
        # on another endpoint would silently full-refresh under an incremental label.
        assert set(INCREMENTAL_ENDPOINTS) == {"orders"}

    def test_source_for_pipeline_rejects_unknown_schema(self):
        inputs = mock.MagicMock()
        inputs.schema_name = "nonexistent"

        with pytest.raises(ValueError, match="Unknown pretix schema"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pretix.source.pretix_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_pretix_source):
        manager = mock.MagicMock()
        inputs = mock.MagicMock()
        inputs.schema_name = "orders"
        inputs.team_id = self.team_id
        inputs.job_id = "job-123"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = "last_modified"

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_pretix_source.assert_called_once_with(
            api_token=self.config.api_token,
            organizer=self.config.organizer,
            base_url=self.config.base_url,
            endpoint="orders",
            team_id=self.team_id,
            job_id="job-123",
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            incremental_field="last_modified",
        )

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pretix.source.pretix_source")
    def test_source_for_pipeline_nulls_last_value_when_not_incremental(self, mock_pretix_source):
        manager = mock.MagicMock()
        inputs = mock.MagicMock()
        inputs.schema_name = "events"
        inputs.team_id = self.team_id
        inputs.logger = mock.MagicMock()
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, manager, inputs)

        _, kwargs = mock_pretix_source.call_args
        assert kwargs["db_incremental_field_last_value"] is None
        assert kwargs["should_use_incremental_field"] is False
