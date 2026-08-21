from typing import Any

from unittest import mock
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.koyeb import KoyebSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.koyeb import source as koyeb_source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.koyeb.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.koyeb.source import KoyebSource
from products.warehouse_sources.backend.types import IncrementalFieldType


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


class TestKoyebSource:
    def setup_method(self) -> None:
        self.source = KoyebSource()
        self.config = KoyebSourceConfig(api_token="token")

    def test_get_schemas_incremental_only_for_instances(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, team_id=1)}
        assert set(schemas) == set(ENDPOINTS)

        instances = schemas["instances"]
        assert instances.supports_incremental is True
        assert instances.supports_append is True
        assert [f["field"] for f in instances.incremental_fields] == ["created_at"]
        assert instances.incremental_fields[0]["field_type"] == IncrementalFieldType.DateTime

        for name, schema in schemas.items():
            if name == "instances":
                continue
            assert schema.supports_incremental is False, name
            assert schema.incremental_fields == [], name

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        captured: dict[str, Any] = {}

        def fake_koyeb_source(**kwargs: Any):
            captured.update(kwargs)
            return MagicMock(name="source_response")

        manager = MagicMock()
        inputs = _source_inputs(
            "instances",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-05-01T00:00:00Z",
            incremental_field="created_at",
        )

        with mock.patch.object(koyeb_source_module, "koyeb_source", fake_koyeb_source):
            self.source.source_for_pipeline(self.config, manager, inputs)

        assert captured["api_token"] == "token"
        assert captured["endpoint"] == "instances"
        assert captured["should_use_incremental_field"] is True
        assert captured["db_incremental_field_last_value"] == "2024-05-01T00:00:00Z"
        assert captured["resumable_source_manager"] is manager

    def test_source_for_pipeline_omits_last_value_when_not_incremental(self) -> None:
        captured: dict[str, Any] = {}

        def fake_koyeb_source(**kwargs: Any):
            captured.update(kwargs)
            return MagicMock()

        inputs = _source_inputs("apps", should_use_incremental_field=False, db_incremental_field_last_value="stale")
        with mock.patch.object(koyeb_source_module, "koyeb_source", fake_koyeb_source):
            self.source.source_for_pipeline(self.config, MagicMock(), inputs)

        assert captured["db_incremental_field_last_value"] is None
