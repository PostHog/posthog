from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.nuntly import NuntlySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.nuntly.source import NuntlySource


class TestNuntlySource:
    def setup_method(self) -> None:
        self.source = NuntlySource()
        self.team_id = 123
        self.config = NuntlySourceConfig(api_key="apk_test")

    @parameterized.expand(
        [
            (True, True, None),
            (False, False, "Invalid credentials"),
        ]
    )
    def test_validate_credentials(self, probe_valid: bool, expected_valid: bool, expected_message: str | None) -> None:
        with scripted_network([ScriptedResponse(status=200 if probe_valid else 401)]) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert len(network.requests_log) == 1
        assert network.requests_log[0].headers["authorization"] == "Bearer apk_test"
        assert network.session_options[0]["redact_values"] == ("apk_test",)
