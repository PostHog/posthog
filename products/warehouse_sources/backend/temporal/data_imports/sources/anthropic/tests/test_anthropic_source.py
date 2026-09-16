from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.settings import ANTHROPIC_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.source import AnthropicSource

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.source"
_CHECK_ANALYTICS_ACCESS = f"{_SOURCE_MODULE}.check_analytics_access"
_CHECK_RBAC_GROUP_ACCESS = f"{_SOURCE_MODULE}.check_rbac_group_access"
_CHECK_RBAC_ROLE_ACCESS = f"{_SOURCE_MODULE}.check_rbac_role_access"


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
            "claude_code_analytics",
            "claude_code_model_breakdown",
            "analytics_user_activity",
            "analytics_user_cost",
            "analytics_user_usage",
            "analytics_connector_usage",
            "analytics_plugin_usage",
            "analytics_skill_usage",
            "analytics_summaries",
            "rbac_groups",
            "rbac_group_members",
            "rbac_roles",
            "rbac_role_permissions",
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
        [
            ("users",),
            ("workspaces",),
            ("api_keys",),
            ("workspace_members",),
            ("invites",),
            # The group and role objects carry an `updated_at`, but no endpoint filters on it.
            ("rbac_groups",),
            ("rbac_group_members",),
            ("rbac_roles",),
            ("rbac_role_permissions",),
        ]
    )
    def test_entity_endpoints_are_full_refresh_only(self, endpoint: str) -> None:
        # No updated-since filter exists on the entity lists, so they must not advertise incremental.
        schema = next(s for s in AnthropicSource().get_schemas(MagicMock(), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is False
        assert schema.supports_append is False

    def test_names_filter(self) -> None:
        schemas = AnthropicSource().get_schemas(MagicMock(), team_id=1, names=["usage_report"])
        assert [s.name for s in schemas] == ["usage_report"]

    def test_no_endpoint_targets_an_admin_key_forbidden_path(self) -> None:
        # This source authenticates with an Admin API key, which Anthropic does not accept on its
        # service-account or federation endpoints (those require an org:admin OAuth token). An
        # endpoint targeting one of those paths would fail every sync, so the catalog must exclude it.
        offenders = [
            name
            for name, config in ANTHROPIC_ENDPOINTS.items()
            if "service_accounts" in config.path or "/federation" in config.path
        ]
        assert offenders == []


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
            ("claude_code_analytics", ["id"], "datetime"),
            ("claude_code_model_breakdown", ["id"], "datetime"),
            ("analytics_user_activity", ["id"], "datetime"),
            ("analytics_user_cost", ["id"], "datetime"),
            ("analytics_user_usage", ["id"], "datetime"),
            ("analytics_connector_usage", ["id"], "datetime"),
            ("analytics_plugin_usage", ["id"], "datetime"),
            ("analytics_skill_usage", ["id"], "datetime"),
            ("analytics_summaries", ["starting_at"], "datetime"),
            ("rbac_groups", ["id"], "datetime"),
            ("rbac_group_members", ["group_id", "user_id"], "datetime"),
            ("rbac_roles", ["id"], "datetime"),
            ("rbac_role_permissions", ["id"], None),
        ]
    )
    def test_primary_keys_and_partitioning(
        self, endpoint: str, primary_keys: list[str], partition_mode: str | None
    ) -> None:
        response = self._response(endpoint)
        assert response.name == endpoint  # type: ignore[attr-defined]
        assert response.primary_keys == primary_keys  # type: ignore[attr-defined]
        assert response.sort_mode == "asc"  # type: ignore[attr-defined]
        # workspace_members and rbac_role_permissions carry no stable timestamp field, so they are
        # not partitioned.
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


class TestAnalyticsEndpointPermissions:
    @patch(_CHECK_ANALYTICS_ACCESS, return_value="needs read:analytics")
    def test_only_the_analytics_tables_carry_the_probe_result(self, _probe) -> None:
        permissions = AnthropicSource().get_endpoint_permissions(
            MagicMock(api_key="sk-ant-admin-test"), team_id=1, endpoints=["users", "analytics_user_cost"]
        )
        assert permissions == {"users": None, "analytics_user_cost": "needs read:analytics"}

    @patch(_CHECK_ANALYTICS_ACCESS)
    def test_no_probe_when_no_analytics_table_is_requested(self, probe) -> None:
        # The probe is a live request, so schema discovery must not pay for it unless a table needs it.
        permissions = AnthropicSource().get_endpoint_permissions(
            MagicMock(api_key="sk-ant-admin-test"), team_id=1, endpoints=["users", "cost_report"]
        )
        assert permissions == {"users": None, "cost_report": None}
        probe.assert_not_called()

    @patch(_CHECK_RBAC_ROLE_ACCESS, return_value="needs read:members")
    @patch(_CHECK_RBAC_GROUP_ACCESS, return_value="needs read:rbac_groups")
    @patch(_CHECK_ANALYTICS_ACCESS, return_value="needs read:analytics")
    def test_each_family_reports_its_own_scope(self, _analytics, _groups, _roles) -> None:
        # The three families take different credentials, so a table must carry its own family's
        # reason. Reporting one family's result against another tells the customer to fix the wrong
        # key.
        permissions = AnthropicSource().get_endpoint_permissions(
            MagicMock(api_key="sk-ant-admin-test"),
            team_id=1,
            endpoints=["analytics_summaries", "rbac_groups", "rbac_group_members", "rbac_role_permissions", "users"],
        )
        assert permissions == {
            "analytics_summaries": "needs read:analytics",
            "rbac_groups": "needs read:rbac_groups",
            "rbac_group_members": "needs read:rbac_groups",
            "rbac_role_permissions": "needs read:members",
            "users": None,
        }

    @patch(_CHECK_RBAC_ROLE_ACCESS)
    @patch(_CHECK_RBAC_GROUP_ACCESS, return_value=None)
    @patch(_CHECK_ANALYTICS_ACCESS)
    def test_one_probe_answers_for_every_table_in_a_family(self, analytics, groups, roles) -> None:
        AnthropicSource().get_endpoint_permissions(
            MagicMock(api_key="sk-ant-admin-test"), team_id=1, endpoints=["rbac_groups", "rbac_group_members"]
        )
        assert groups.call_count == 1
        analytics.assert_not_called()
        roles.assert_not_called()
