from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.cursor.cursor import KEY_REJECTED_MESSAGE
from products.warehouse_sources.backend.temporal.data_imports.sources.cursor.source import CursorSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cursor import CursorSourceConfig


class TestCursorSource:
    def setup_method(self):
        self.source = CursorSource()
        self.config = CursorSourceConfig(api_key="key_test")
        self.team_id = 123

    @parameterized.expand(
        [
            ("members", False, None),
            ("daily_usage", True, "date"),
            ("usage_events", True, "timestamp"),
            ("spend", False, None),
            ("agent_edits", True, "event_date"),
            ("tabs", True, "event_date"),
            ("dau", True, "date"),
            ("models", True, "date"),
            ("top_file_extensions", True, "event_date"),
            ("by_user_agent_edits", True, "event_date"),
            ("by_user_tabs", True, "event_date"),
            ("by_user_models", True, "date"),
            ("by_user_top_file_extensions", True, "event_date"),
            ("ai_code_commits", True, "commitTs"),
            ("ai_code_changes", True, "createdAt"),
        ]
    )
    def test_get_schemas_incremental_support(self, endpoint, supports_incremental, incremental_field):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        schema = schemas[endpoint]

        assert schema.supports_incremental is supports_incremental
        assert schema.supports_append is supports_incremental
        if incremental_field:
            assert [f["field"] for f in schema.incremental_fields] == [incremental_field]
        else:
            assert schema.incremental_fields == []

    def test_get_schemas_filters_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["members", "spend"])

        assert [s.name for s in schemas] == ["members", "spend"]

    @parameterized.expand([((True, None),), ((False, KEY_REJECTED_MESSAGE),)])
    def test_validate_credentials(self, probe_result):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.cursor.source.validate_cursor_credentials",
            return_value=probe_result,
        ):
            assert self.source.validate_credentials(self.config, self.team_id) == probe_result
