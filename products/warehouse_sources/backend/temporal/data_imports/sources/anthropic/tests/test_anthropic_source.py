from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.source import AnthropicSource


class TestAnthropicSchemas:
    def test_all_endpoints_present(self) -> None:
        names = {s.name for s in AnthropicSource().get_schemas(MagicMock(), team_id=1)}
        assert names == {
            "users",
            "invites",
            "workspaces",
            "api_keys",
            "workspace_members",
            "service_accounts",
            "usage_report",
            "cost_report",
            "claude_code_analytics",
            "claude_code_model_breakdown",
        }

    @parameterized.expand([("usage_report",), ("cost_report",)])
    def test_report_endpoints_are_incremental_on_starting_at(self, endpoint: str) -> None:
        # Only the report endpoints have a genuine server-side time filter (starting_at).
        schema = next(s for s in AnthropicSource().get_schemas(MagicMock(), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is True
        assert schema.supports_append is False  # buckets get restated; append would duplicate
        assert [f["field"] for f in schema.incremental_fields] == ["starting_at"]
        assert schema.default_incremental_lookback_seconds == 60 * 60 * 24

    @parameterized.expand([("claude_code_analytics",), ("claude_code_model_breakdown",)])
    def test_claude_code_endpoints_are_incremental_on_date(self, endpoint: str) -> None:
        # The Claude Code endpoint windows on a single `starting_at` day, so `date` is the watermark.
        schema = next(s for s in AnthropicSource().get_schemas(MagicMock(), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is True
        assert schema.supports_append is False  # the current day keeps accruing; append would duplicate
        assert [f["field"] for f in schema.incremental_fields] == ["date"]
        assert schema.default_incremental_lookback_seconds == 60 * 60 * 24

    @parameterized.expand(
        [("users",), ("workspaces",), ("api_keys",), ("workspace_members",), ("invites",), ("service_accounts",)]
    )
    def test_entity_endpoints_are_full_refresh_only(self, endpoint: str) -> None:
        # No updated-since filter exists on the entity lists, so they must not advertise incremental.
        schema = next(s for s in AnthropicSource().get_schemas(MagicMock(), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is False
        assert schema.supports_append is False

    def test_names_filter(self) -> None:
        schemas = AnthropicSource().get_schemas(MagicMock(), team_id=1, names=["usage_report"])
        assert [s.name for s in schemas] == ["usage_report"]
