import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.browser_use import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.browser_use.settings import (
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
