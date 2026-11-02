import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.eventee.source import EventeeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.eventee import (
    EventeeSourceConfig,
)


class TestEventeeSource:
    def setup_method(self) -> None:
        self.source = EventeeSource()
        self.team_id = 123
        self.config = EventeeSourceConfig(api_key="tok")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Eventee API token"),
        ],
    )
    def test_validate_credentials(self, mock_return: bool, expected_valid: bool, expected_message: str | None) -> None:
        status = 200 if mock_return else 401
        with scripted_network([ScriptedResponse(status=status)]) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert len(network.requests_log) == 1
        assert network.requests_log[0].headers["authorization"] == "Bearer tok"
