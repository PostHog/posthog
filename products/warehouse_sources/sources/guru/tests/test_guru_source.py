import pytest

from products.warehouse_sources.sources.guru._config import GuruSourceConfig
from products.warehouse_sources.sources.guru.source import GuruSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, scripted_network


class TestGuruSource:
    def setup_method(self) -> None:
        self.source = GuruSource()
        self.team_id = 123
        self.config = GuruSourceConfig(username="user@company.com", api_token="api-token")

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
        ],
    )
    def test_validate_credentials(self, status: int, expected_valid: bool, expected_message: str | None) -> None:
        with scripted_network([ScriptedResponse(status=status, json={"team": {"id": "team-1"}})]) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert [request.path for request in network.requests_log] == ["/api/v1/whoami"]
        assert network.requests_log[0].headers["authorization"].startswith("Basic ")
