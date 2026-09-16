import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.browser_use import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.browser_use.settings import (
    BROWSER_USE_API_VERSION_V3,
    BROWSER_USE_API_VERSION_V4,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.browser_use.source import BrowserUseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.browseruse import (
    BrowserUseSourceConfig,
)


class TestBrowserUseSource:
    def setup_method(self) -> None:
        self.source = BrowserUseSource()
        self.config = BrowserUseSourceConfig(api_key="bu_test")

    def test_default_version_is_v4(self) -> None:
        # New sources must start on v4 (declared newest-last, default flipped to it) and, with no
        # pin, discover the v4 catalog.
        assert self.source.supported_versions == (BROWSER_USE_API_VERSION_V3, BROWSER_USE_API_VERSION_V4)
        assert self.source.default_version == BROWSER_USE_API_VERSION_V4
        names = {s.name for s in self.source.get_schemas(self.config, team_id=1)}
        assert names == {"sessions", "runs", "browser_sessions", "profiles"}

    @parameterized.expand(
        [
            (
                BROWSER_USE_API_VERSION_V3,
                {"sessions", "browser_sessions", "profiles", "workspaces", "session_messages"},
            ),
            (BROWSER_USE_API_VERSION_V4, {"sessions", "runs", "browser_sessions", "profiles"}),
        ]
    )
    def test_schemas_match_version_catalog(self, version: str, expected: set[str]) -> None:
        # A pinned source discovers only its own version's tables — v4 drops the workspaces list and
        # session_messages and adds runs. No list endpoint in either version has a since-filter, so
        # advertising incremental/append would offer a mode that still scans everything.
        schemas = self.source.get_schemas(self.config, team_id=1, api_version=version)
        assert {s.name for s in schemas} == expected
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_session_messages_off_by_default_on_v3(self) -> None:
        # session_messages fans out one request per session, so it must stay opt-in to avoid
        # surprise API cost; the top-level lists stay on.
        schemas = {
            s.name: s for s in self.source.get_schemas(self.config, team_id=1, api_version=BROWSER_USE_API_VERSION_V3)
        }
        assert schemas["session_messages"].should_sync_default is False
        assert schemas["sessions"].should_sync_default is True

    def test_names_filter_narrows_schemas(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["sessions"])
        assert [s.name for s in schemas] == ["sessions"]

    def test_documented_tables_render_for_public_docs(self) -> None:
        # Public docs render the default (v4) catalog, so lists_tables_without_credentials must
        # surface those tables (with canonical descriptions) for the posthog.com Supported tables
        # section — including the new runs table.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        by_name = {t["name"]: t for t in tables}
        assert set(by_name) == {"sessions", "runs", "browser_sessions", "profiles"}
        assert by_name["sessions"]["sync_methods"] == ["Full refresh"]
        assert by_name["runs"]["description"]

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

    def test_source_for_pipeline_passes_api_key_schema_and_resolved_version(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "sessions"
        inputs.api_version = None  # no pin resolves to the default (v4)
        manager = mock.MagicMock()
        with mock.patch.object(source_module, "browser_use_source") as mock_source:
            self.source.source_for_pipeline(self.config, manager, inputs)
        mock_source.assert_called_once()
        _, kwargs = mock_source.call_args
        assert kwargs["api_key"] == "bu_test"
        assert kwargs["endpoint"] == "sessions"
        assert kwargs["api_version"] == BROWSER_USE_API_VERSION_V4

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        # An arbitrary schema name must raise a controlled ValueError rather than crashing the
        # worker with an uncaught KeyError when indexing the endpoint catalog.
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_real_endpoint"
        inputs.api_version = None
        manager = mock.MagicMock()
        with pytest.raises(ValueError, match="Unknown Browser Use schema"):
            self.source.source_for_pipeline(self.config, manager, inputs)

    def test_source_for_pipeline_rejects_schema_absent_in_pinned_version(self) -> None:
        # A v4-pinned source must not serve a v3-only endpoint: session_messages has no v4 list
        # endpoint, so requesting it under v4 must fail loudly rather than 404 mid-sync.
        inputs = mock.MagicMock()
        inputs.schema_name = "session_messages"
        inputs.api_version = BROWSER_USE_API_VERSION_V4
        manager = mock.MagicMock()
        with pytest.raises(ValueError, match="Unknown Browser Use schema"):
            self.source.source_for_pipeline(self.config, manager, inputs)
