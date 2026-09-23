from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.facade.source_config import SourceFieldInputConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.cursor.cursor import KEY_REJECTED_MESSAGE
from products.warehouse_sources.backend.temporal.data_imports.sources.cursor.source import CursorSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cursor import CursorSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

ALL_ENDPOINTS = [
    "members",
    "daily_usage",
    "usage_events",
    "spend",
    "agent_edits",
    "tabs",
    "dau",
    "models",
    "top_file_extensions",
    "by_user_agent_edits",
    "by_user_tabs",
    "by_user_models",
    "by_user_top_file_extensions",
    "ai_code_commits",
    "ai_code_changes",
]


class TestCursorSource:
    def setup_method(self):
        self.source = CursorSource()
        self.config = CursorSourceConfig(api_key="key_test")
        self.team_id = 123

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name == ExternalDataSourceType.CURSOR
        assert config.label == "Cursor"
        field = config.fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert len(config.fields) == 1
        assert field.name == "api_key"
        assert field.required is True
        assert field.secret is True
        # The docs slug is derived from docsUrl; a mismatch 404s the public doc.
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/cursor"

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert [s.name for s in schemas] == ALL_ENDPOINTS

    def test_enterprise_only_endpoints_are_not_selected_by_default(self):
        # The Analytics and AI code tracking APIs need an Enterprise plan, so a Business-plan team
        # that accepts the defaults must not end up with schemas that 403 on every sync.
        defaults = {s.name: s.should_sync_default for s in self.source.get_schemas(self.config, self.team_id)}

        assert [name for name, default in defaults.items() if default] == [
            "members",
            "daily_usage",
            "usage_events",
            "spend",
        ]

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

    def test_get_documented_tables_lists_endpoints_without_credentials(self):
        # lists_tables_without_credentials=True drives the public docs' Supported tables section.
        tables = self.source.get_documented_tables()

        assert [t["name"] for t in tables] == ALL_ENDPOINTS
        assert all(t["description"] for t in tables)

    @parameterized.expand([((True, None),), ((False, KEY_REJECTED_MESSAGE),)])
    def test_validate_credentials(self, probe_result):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.cursor.source.validate_cursor_credentials",
            return_value=probe_result,
        ):
            assert self.source.validate_credentials(self.config, self.team_id) == probe_result
