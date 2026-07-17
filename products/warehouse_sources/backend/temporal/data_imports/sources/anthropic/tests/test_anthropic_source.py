from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceFieldInputConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.anthropic import AnthropicResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.source import AnthropicSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestAnthropicSourceConfig:
    def test_source_type(self) -> None:
        assert AnthropicSource().source_type == ExternalDataSourceType.ANTHROPIC

    def test_config_exposes_single_secret_api_key_field(self) -> None:
        config = AnthropicSource().get_source_config
        assert config.name == SchemaExternalDataSourceType.ANTHROPIC
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/anthropic"
        assert config.unreleasedSource is None
        fields = [f for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert [f.name for f in fields] == ["api_key"]
        assert fields[0].secret is True and fields[0].required is True


class TestAnthropicSchemas:
    def test_all_endpoints_present(self) -> None:
        names = {s.name for s in AnthropicSource().get_schemas(MagicMock(), team_id=1)}
        assert names == {
            "users",
            "invites",
            "workspaces",
            "api_keys",
            "workspace_members",
            "usage_report",
            "cost_report",
        }

    @parameterized.expand([("usage_report",), ("cost_report",)])
    def test_report_endpoints_are_incremental_on_starting_at(self, endpoint: str) -> None:
        # Only the report endpoints have a genuine server-side time filter (starting_at).
        schema = next(s for s in AnthropicSource().get_schemas(MagicMock(), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is True
        assert schema.supports_append is False  # buckets get restated; append would duplicate
        assert [f["field"] for f in schema.incremental_fields] == ["starting_at"]
        assert schema.default_incremental_lookback_seconds == 60 * 60 * 24

    @parameterized.expand([("users",), ("workspaces",), ("api_keys",), ("workspace_members",), ("invites",)])
    def test_entity_endpoints_are_full_refresh_only(self, endpoint: str) -> None:
        # No updated-since filter exists on the entity lists, so they must not advertise incremental.
        schema = next(s for s in AnthropicSource().get_schemas(MagicMock(), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is False
        assert schema.supports_append is False

    def test_names_filter(self) -> None:
        schemas = AnthropicSource().get_schemas(MagicMock(), team_id=1, names=["usage_report"])
        assert [s.name for s in schemas] == ["usage_report"]


class TestAnthropicResumableManager:
    def test_manager_bound_to_resume_config(self) -> None:
        inputs = MagicMock()
        manager = AnthropicSource().get_resumable_source_manager(inputs)
        assert manager._data_class is AnthropicResumeConfig


class TestAnthropicSourceForPipeline:
    def _response(self, endpoint: str) -> object:
        inputs = MagicMock()
        inputs.schema_name = endpoint
        inputs.logger = MagicMock()
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = None
        config = MagicMock(api_key="sk-ant-admin-test")
        return AnthropicSource().source_for_pipeline(config, MagicMock(), inputs)

    @parameterized.expand(
        [
            ("usage_report", ["id"], "datetime"),
            ("cost_report", ["id"], "datetime"),
            ("users", ["id"], "datetime"),
            ("workspace_members", ["workspace_id", "user_id"], None),
        ]
    )
    def test_primary_keys_and_partitioning(
        self, endpoint: str, primary_keys: list[str], partition_mode: str | None
    ) -> None:
        response = self._response(endpoint)
        assert response.name == endpoint  # type: ignore[attr-defined]
        assert response.primary_keys == primary_keys  # type: ignore[attr-defined]
        assert response.sort_mode == "asc"  # type: ignore[attr-defined]
        # workspace_members has no stable timestamp field, so it is not partitioned.
        assert response.partition_mode == partition_mode  # type: ignore[attr-defined]


class TestDocumentedTables:
    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog => the source opts into publishing its table list to public docs.
        assert AnthropicSource().lists_tables_without_credentials is True
        tables = AnthropicSource().get_documented_tables()
        names = {t["name"] for t in tables}
        assert "usage_report" in names and "cost_report" in names
        usage = next(t for t in tables if t["name"] == "usage_report")
        assert "Incremental" in usage["sync_methods"]
        assert usage["description"]  # canonical description is surfaced
