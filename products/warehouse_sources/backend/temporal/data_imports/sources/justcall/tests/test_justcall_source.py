import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.justcall import (
    JustCallSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.justcall.source import JustCallSource


class TestJustCallSource:
    def setup_method(self) -> None:
        self.source = JustCallSource()
        self.team_id = 123
        self.config = JustCallSourceConfig(api_key="key", api_secret="secret")

    def test_lists_tables_without_credentials(self) -> None:
        # The endpoint catalog is static (no I/O), so it's safe to render in public docs.
        assert JustCallSource.lists_tables_without_credentials is True

    @pytest.mark.parametrize(
        "probe_result, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid JustCall API credentials"),
        ],
    )
    def test_validate_credentials(self, probe_result: bool, expected_valid: bool, expected_message: str | None) -> None:
        status_code = 200 if probe_result else 401
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert message == expected_message
        assert len(network.requests_log) == 1
        assert network.requests_log[0].headers["authorization"] == "key:secret"
