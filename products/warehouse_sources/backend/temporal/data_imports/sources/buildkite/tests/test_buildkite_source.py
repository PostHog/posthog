from typing import Any

from unittest import mock
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.source import BuildkiteSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.buildkite import (
    BuildkiteSourceConfig,
)


def _config() -> BuildkiteSourceConfig:
    return BuildkiteSourceConfig(api_access_token="bkua_test", organization="my-org")


class TestBuildkiteSource:
    def setup_method(self) -> None:
        self.source = BuildkiteSource()
        self.team_id = 123

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "builds"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = "created_at"
        manager = MagicMock()

        captured: dict[str, Any] = {}

        def fake_source(**kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            return MagicMock()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.source.buildkite_source",
            side_effect=fake_source,
        ):
            self.source.source_for_pipeline(_config(), manager, inputs)

        assert captured["api_access_token"] == "bkua_test"
        assert captured["organization"] == "my-org"
        assert captured["endpoint"] == "builds"
        assert captured["team_id"] is inputs.team_id
        assert captured["job_id"] is inputs.job_id
        assert captured["should_use_incremental_field"] is True
        assert captured["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
        assert captured["incremental_field"] == "created_at"
        assert captured["resumable_source_manager"] is manager

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "pipelines"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = None

        captured: dict[str, Any] = {}

        def fake_source(**kwargs: Any) -> str:
            captured.update(kwargs)
            return "response"

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.source.buildkite_source",
            side_effect=fake_source,
        ):
            self.source.source_for_pipeline(_config(), MagicMock(), inputs)

        assert captured["db_incremental_field_last_value"] is None
