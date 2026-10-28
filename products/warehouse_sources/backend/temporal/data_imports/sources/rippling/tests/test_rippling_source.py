import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rippling import (
    RipplingSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rippling.settings import RIPPLING_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.rippling.source import RipplingSource


class TestRipplingSource:
    def setup_method(self):
        self.source = RipplingSource()
        self.team_id = 123
        self.config = RipplingSourceConfig(api_token="api-token")

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
        ],
    )
    def test_validate_credentials(self, status, expected_valid, expected_message):
        with scripted_network(always(ScriptedResponse(status=status, json={}))) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert network.requests_log[0].headers["authorization"] == "Bearer api-token"

    def test_version_declaration_defaults_to_v2_with_v1_supported(self):
        # Rippling's REST API version is bound to the token account-side, so both labels issue the
        # same requests; the default tracks the newest label without repinning existing v1 sources.
        assert self.source.supported_versions == ("v1", "v2")
        assert self.source.default_version == "v2"
        assert self.source.deprecated_versions == ()

    @pytest.mark.parametrize("pinned_version", [None, "v1", "v2"])
    @pytest.mark.parametrize("endpoint", ["workers", "work_locations"])
    def test_request_path_is_identical_for_every_version(self, endpoint, pinned_version):
        # The pin only records which Rippling tier a source targets; it must never change the wire.
        # A future v2 branch that switched paths or injected a `Rippling-Api-Version` header would
        # break existing v1 syncs and silently override the customer's token-bound version.
        result = SourceDriver(self.source, self.config).run(
            endpoint,
            [ScriptedResponse(json={"results": [], "next_link": None})],
            api_version=pinned_version,
        )

        assert result.requests, "expected at least one request"
        assert result.requests[0].path == RIPPLING_ENDPOINTS[endpoint].path
        assert "rippling-api-version" not in result.requests[0].headers
