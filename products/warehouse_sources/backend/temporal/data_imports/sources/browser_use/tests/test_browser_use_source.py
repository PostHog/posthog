import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.browser_use import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.browser_use.browser_use import (
    BrowserUseResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.browser_use.source import BrowserUseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BrowserUseSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestBrowserUseSource:
    def setup_method(self) -> None:
        self.source = BrowserUseSource()
        self.config = BrowserUseSourceConfig(api_key="bu_test")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.BROWSERUSE

    def test_config_exposes_api_key_field(self) -> None:
        fields = self.source.get_source_config.fields
        assert [f.name for f in fields] == ["api_key"]

    @parameterized.expand(
        [
            ("sessions", True),
            ("browser_sessions", True),
            ("profiles", True),
            ("workspaces", True),
            ("session_messages", False),
        ]
    )
    def test_schemas_are_full_refresh_only(self, endpoint: str, default_on: bool) -> None:
        # The v3 list endpoints expose no server-side since-filter, so advertising incremental or
        # append would offer a mode that still scans everything. session_messages fans out per
        # session, so it must stay off by default to avoid surprise API cost.
        schemas = {s.name: s for s in self.source.get_schemas(self.config, team_id=1)}

        assert set(schemas) == {"sessions", "browser_sessions", "profiles", "workspaces", "session_messages"}
        schema = schemas[endpoint]
        assert schema.supports_incremental is False
        assert schema.supports_append is False
        assert schema.incremental_fields == []
        assert schema.should_sync_default is default_on

    def test_names_filter_narrows_schemas(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["sessions"])
        assert [s.name for s in schemas] == ["sessions"]

    def test_documented_tables_render_for_public_docs(self) -> None:
        # get_schemas is a static catalog, so lists_tables_without_credentials must surface the
        # tables (with canonical descriptions) for the posthog.com Supported tables section.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        by_name = {t["name"]: t for t in tables}
        assert set(by_name) == {"sessions", "browser_sessions", "profiles", "workspaces", "session_messages"}
        assert by_name["sessions"]["sync_methods"] == ["Full refresh"]
        assert by_name["sessions"]["description"]

    @parameterized.expand(
        [
            ("401", "401 Client Error: Unauthorized for url: https://api.browser-use.com/api/v3/sessions?page=1"),
            ("403", "403 Client Error: Forbidden for url: https://api.browser-use.com/api/v3/sessions?page=1"),
        ]
    )
    def test_permission_errors_are_non_retryable(self, _name: str, observed: str) -> None:
        # 401 (bad key) and 403 (key without access) can never be satisfied by a retry, so both must
        # be classified terminal with an actionable message instead of looping the sync.
        assert any(key in observed for key in self.source.get_non_retryable_errors())

    @parameterized.expand([("valid", True, True, None), ("invalid", False, False, "Invalid Browser Use API key")])
    def test_validate_credentials(
        self, _name: str, probe_result: bool, expected_valid: bool, expected_message: str | None
    ) -> None:
        with mock.patch.object(source_module, "validate_browser_use_credentials", return_value=probe_result):
            valid, message = self.source.validate_credentials(self.config, team_id=1)
        assert valid is expected_valid
        assert message == expected_message

    def test_resumable_manager_bound_to_resume_config(self) -> None:
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is BrowserUseResumeConfig

    def test_source_for_pipeline_passes_api_key_and_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "sessions"
        manager = mock.MagicMock()
        with mock.patch.object(source_module, "browser_use_source") as mock_source:
            self.source.source_for_pipeline(self.config, manager, inputs)
        mock_source.assert_called_once()
        _, kwargs = mock_source.call_args
        assert kwargs["api_key"] == "bu_test"
        assert kwargs["endpoint"] == "sessions"

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        # An arbitrary schema name must raise a controlled ValueError rather than crashing the
        # worker with an uncaught KeyError when indexing the endpoint catalog.
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_real_endpoint"
        manager = mock.MagicMock()
        with pytest.raises(ValueError, match="Unknown Browser Use schema"):
            self.source.source_for_pipeline(self.config, manager, inputs)
