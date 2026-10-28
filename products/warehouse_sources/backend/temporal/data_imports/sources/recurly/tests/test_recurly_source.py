from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.recurly import (
    RecurlySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recurly.source import RecurlySource

_EMPTY_PAGE = ScriptedResponse(json={"object": "list", "has_more": False, "next": None, "data": [{"id": "r1"}]})


class TestRecurlySource:
    def setup_method(self):
        self.source = RecurlySource()
        self.team_id = 123
        self.config = RecurlySourceConfig(api_key="test-key", region="us")
        self.driver = SourceDriver(self.source, self.config)

    def test_source_for_pipeline_plumbs_inputs(self):
        result = self.driver.run(
            "accounts",
            [_EMPTY_PAGE],
            incremental_field="updated_at",
            db_incremental_field_last_value="2024-01-01T00:00:00Z",
        )

        assert result.requests[0].param("begin_time") == "2024-01-01T00:00:00Z"
        assert result.requests[0].param("sort") == "updated_at"
        assert result.response is not None
        assert result.response.name == "accounts"
        assert result.response.primary_keys == ["id"]
        assert result.response.partition_mode == "datetime"
        assert result.response.partition_keys == ["created_at"]
        assert result.response.sort_mode == "asc"

    def test_source_for_pipeline_drops_last_value_on_full_refresh(self):
        result = self.driver.run(
            "plans",
            [_EMPTY_PAGE],
            db_incremental_field_last_value="2024-01-01T00:00:00Z",
        )

        # When the user isn't running incrementally, no watermark should leak through.
        assert result.requests[0].param("begin_time") is None
