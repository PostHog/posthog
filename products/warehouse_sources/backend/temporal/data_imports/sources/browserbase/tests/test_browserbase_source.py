from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.browserbase import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.browserbase.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.browserbase.source import BrowserbaseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.browserbase import (
    BrowserbaseSourceConfig,
)


def _config() -> BrowserbaseSourceConfig:
    return BrowserbaseSourceConfig(api_key="bb_test_key")


class TestBrowserbaseSchemas:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_every_endpoint_is_full_refresh_only(self, endpoint: str) -> None:
        # No Browserbase endpoint exposes a usable incremental cursor: most have no server-side
        # timestamp filter at all, and the agent endpoints only filter on creation time over rows
        # that keep changing afterwards. Guards against a future edit flipping this on.
        schema = next(s for s in BrowserbaseSource().get_schemas(_config(), team_id=1) if s.name == endpoint)

        assert schema.supports_incremental is False
        assert schema.supports_append is False
        assert schema.incremental_fields == []


class TestBrowserbaseCredentials:
    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    @patch.object(source_module, "validate_browserbase_credentials")
    def test_validate_credentials(
        self, _name: str, probe_result: bool, expected_ok: bool, mock_validate: MagicMock
    ) -> None:
        mock_validate.return_value = probe_result

        ok, error = BrowserbaseSource().validate_credentials(_config(), team_id=1)

        assert ok is expected_ok
        assert (error is None) is expected_ok


class TestBrowserbasePipelineHandoff:
    def test_source_for_pipeline_plumbs_endpoint_and_key(self) -> None:
        result = SourceDriver(BrowserbaseSource(), _config()).run(
            "sessions",
            [ScriptedResponse(json=[{"id": "sess_1", "createdAt": "2026-01-01T00:00:00Z"}])],
            team_id=1,
            job_id="job_1",
        )

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == "sessions"
        assert result.response.primary_keys == ["id"]

        # The items thunk should actually pull rows using the configured key/endpoint.
        assert result.items == [[{"id": "sess_1", "createdAt": "2026-01-01T00:00:00Z"}]]
        assert result.requests[0].headers["x-bb-api-key"] == "bb_test_key"
