from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.trunkio import (
    TrunkIoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trunk_io.source import TrunkIoSource


def _make_inputs(schema_name: str, **overrides) -> SourceInputs:
    defaults: dict = {
        "schema_name": schema_name,
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 123,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestTrunkIoSource:
    def setup_method(self):
        self.source = TrunkIoSource()
        self.team_id = 123
        self.config = TrunkIoSourceConfig(
            api_token="test-token",
            org_url_slug="my-org",
            repo_host="github.com",
            repo_owner="my-org",
            repo_name="my-repo",
            merge_queue_target_branch="main",
        )

    def test_source_for_pipeline_unknown_endpoint_raises(self):
        inputs = _make_inputs("NotARealEndpoint")
        manager = MagicMock(spec=ResumableSourceManager)

        try:
            self.source.source_for_pipeline(self.config, manager, inputs)
            raised = False
        except ValueError:
            raised = True

        assert raised
