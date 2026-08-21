import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.retently import (
    RetentlySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.retently import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.retently.source import RetentlySource


class TestGetSchemas:
    def setup_method(self) -> None:
        self.schemas = {s.name: s for s in RetentlySource().get_schemas(MagicMock(), team_id=1)}

    def test_all_expected_tables_present(self) -> None:
        assert set(self.schemas) == {
            "customers",
            "companies",
            "feedback",
            "outbox",
            "campaigns",
            "templates",
            "reports",
        }

    def test_feedback_is_the_only_incremental_table(self) -> None:
        assert self.schemas["feedback"].supports_incremental is True
        assert [f["field"] for f in self.schemas["feedback"].incremental_fields] == ["createdDate"]
        for name, schema in self.schemas.items():
            if name != "feedback":
                assert schema.supports_incremental is False, name
                assert schema.incremental_fields == [], name


class TestResumablePlumbing:
    def test_source_for_pipeline_passes_incremental_inputs(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "feedback"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        config = RetentlySourceConfig(api_key="key")
        manager = MagicMock()

        with patch.object(source_module, "retently_source") as mock_source:
            RetentlySource().source_for_pipeline(config, manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["api_key"] == "key"
        assert kwargs["endpoint"] == "feedback"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "customers"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "ignored"
        config = RetentlySourceConfig(api_key="key")

        with patch.object(source_module, "retently_source") as mock_source:
            RetentlySource().source_for_pipeline(config, MagicMock(), inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "not_a_real_table"
        with pytest.raises(ValueError):
            RetentlySource().source_for_pipeline(RetentlySourceConfig(api_key="key"), MagicMock(), inputs)
