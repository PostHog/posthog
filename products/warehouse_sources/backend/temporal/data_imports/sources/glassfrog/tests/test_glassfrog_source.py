from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.glassfrog import (
    GlassfrogSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.glassfrog import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.glassfrog.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.glassfrog.source import GlassfrogSource


def _config() -> GlassfrogSourceConfig:
    return GlassfrogSourceConfig(api_key="gf_test_key")


class TestGlassfrogSchemas:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_every_endpoint_is_full_refresh_only(self, endpoint: str) -> None:
        # No GlassFrog v3 endpoint exposes a server-side timestamp or cursor filter, so nothing can
        # sync incrementally — guarding against a future edit flipping this on without a real filter.
        schema = next(s for s in GlassfrogSource().get_schemas(_config(), team_id=1) if s.name == endpoint)

        assert schema.supports_incremental is False
        assert schema.supports_append is False
        assert schema.incremental_fields == []


class TestGlassfrogCredentials:
    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    @patch.object(source_module, "validate_glassfrog_credentials")
    def test_validate_credentials(
        self, _name: str, probe_result: bool, expected_ok: bool, mock_validate: MagicMock
    ) -> None:
        mock_validate.return_value = probe_result

        ok, error = GlassfrogSource().validate_credentials(_config(), team_id=1)

        assert ok is expected_ok
        assert (error is None) is expected_ok


class TestGlassfrogPipelineHandoff:
    def test_source_for_pipeline_plumbs_endpoint_and_key(self) -> None:
        result = SourceDriver(GlassfrogSource(), _config()).run(
            "circles", [ScriptedResponse(json={"circles": [{"id": 1, "name": "General Company Circle"}]})]
        )

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == "circles"
        assert result.response.primary_keys == ["id"]

        # The items thunk should actually pull rows using the configured key/endpoint.
        assert result.items == [[{"id": 1, "name": "General Company Circle"}]]
        assert result.requests[0].headers["x-auth-token"] == "gf_test_key"
