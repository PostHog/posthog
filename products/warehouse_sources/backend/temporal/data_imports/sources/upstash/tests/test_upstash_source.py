from typing import Any

from unittest import mock
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.upstash import (
    UpstashSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.upstash import source as upstash_source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.upstash.source import UpstashSource


def _source_inputs(schema_name: str, **overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": schema_name,
        "schema_id": "schema-id",
        "source_id": "source-id",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-id",
        "logger": MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestUpstashSource:
    def setup_method(self) -> None:
        self.source = UpstashSource()
        self.config = UpstashSourceConfig(email="me@example.com", api_key="key")

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        captured: dict[str, Any] = {}

        def fake_upstash_source(**kwargs: Any):
            captured.update(kwargs)
            return MagicMock(name="source_response")

        inputs = _source_inputs("redis_databases")
        with mock.patch.object(upstash_source_module, "upstash_source", fake_upstash_source):
            self.source.source_for_pipeline(self.config, inputs)

        assert captured["email"] == "me@example.com"
        assert captured["api_key"] == "key"
        assert captured["endpoint"] == "redis_databases"
