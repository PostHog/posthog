from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.retently import (
    RetentlySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.retently.source import RetentlySource


class TestRetentlySourceConfig:
    def setup_method(self) -> None:
        self.source = RetentlySource()

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — required for the public-docs table list to render.
        assert self.source.lists_tables_without_credentials is True


class TestGetSchemas:
    def setup_method(self) -> None:
        self.schemas = {s.name: s for s in RetentlySource().get_schemas(MagicMock(), team_id=1)}

    def test_feedback_is_the_only_incremental_table(self) -> None:
        assert self.schemas["feedback"].supports_incremental is True
        assert [f["field"] for f in self.schemas["feedback"].incremental_fields] == ["createdDate"]
        for name, schema in self.schemas.items():
            if name != "feedback":
                assert schema.supports_incremental is False, name
                assert schema.incremental_fields == [], name


class TestResumablePlumbing:
    def setup_method(self) -> None:
        self.driver = SourceDriver(RetentlySource(), RetentlySourceConfig(api_key="key"))

    def test_source_for_pipeline_passes_incremental_inputs(self) -> None:
        result = self.driver.run(
            "feedback",
            [ScriptedResponse(json={"data": {"responses": [], "pages": 0}})],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )

        assert result.requests[0].headers["x-api-key"] == "key"
        assert result.paths == ["/api/v2/feedback"]
        assert result.requests[0].param("startDate") == "2026-01-01T00:00:00Z"

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self) -> None:
        result = self.driver.run(
            "customers",
            [ScriptedResponse(json={"data": {"subscribers": [], "pages": 0}})],
            should_use_incremental_field=False,
            db_incremental_field_last_value="ignored",
        )

        assert "startDate" not in result.requests[0].query
