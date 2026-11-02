from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.bluesky.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.bluesky.source import (
    PARTITION_FIELDS,
    BlueskySource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bluesky import (
    BlueskySourceConfig,
)


class TestBlueskySource:
    def setup_method(self):
        self.source = BlueskySource()
        self.team_id = 123
        self.config = BlueskySourceConfig(actor="jay.bsky.team")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bluesky.source.bluesky_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_bluesky_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "Posts"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_bluesky_source.assert_called_once_with(
            actor="jay.bsky.team",
            endpoint="Posts",
            team_id=self.team_id,
            job_id="job-1",
            resumable_source_manager=manager,
        )

    def test_partition_fields_only_cover_multi_row_endpoints(self):
        # Profile is a single row per sync; partitioning it isn't meaningful.
        assert "Profile" not in PARTITION_FIELDS
        assert set(PARTITION_FIELDS) == set(ENDPOINTS) - {"Profile"}
