from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.browser_use.settings import (
    BROWSER_USE_API_VERSION_V3,
    BROWSER_USE_API_VERSION_V4,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.browser_use.source import BrowserUseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.browseruse import (
    BrowserUseSourceConfig,
)


class TestBrowserUseSource:
    def setup_method(self) -> None:
        self.source = BrowserUseSource()
        self.config = BrowserUseSourceConfig(api_key="bu_test")

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

    @parameterized.expand([("valid", True, True, None), ("invalid", False, False, "Invalid Browser Use API key")])
    def test_validate_credentials(
        self, _name: str, probe_result: bool, expected_valid: bool, expected_message: str | None
    ) -> None:
        status = 200 if probe_result else 401
        with scripted_network([ScriptedResponse(status=status, json={})]):
            valid, message = self.source.validate_credentials(self.config, team_id=1)
        assert valid is expected_valid
        assert message == expected_message

    def test_source_for_pipeline_passes_api_key_schema_and_resolved_version(self) -> None:
        result = SourceDriver(self.source, self.config).run("sessions", [ScriptedResponse(json={"sessions": []})])

        assert result.raised is None
        assert result.requests[0].headers["x-browser-use-api-key"] == "bu_test"
        assert result.paths == ["/api/v4/sessions"]

    def test_source_for_pipeline_rejects_schema_absent_in_pinned_version(self) -> None:
        # A v4-pinned source must not serve a v3-only endpoint: session_messages has no v4 list
        # endpoint, so requesting it under v4 must fail loudly rather than 404 mid-sync.
        result = SourceDriver(self.source, self.config).run(
            "session_messages", [], api_version=BROWSER_USE_API_VERSION_V4
        )

        assert isinstance(result.raised, ValueError)
        assert "Unknown Browser Use schema" in str(result.raised)
