import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.source import BabelforceSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.babelforce import (
    BabelforceSourceConfig,
)


class TestBabelforceSource:
    def setup_method(self) -> None:
        self.source = BabelforceSource()
        self.team_id = 123
        self.config = BabelforceSourceConfig(environment="services", access_id="access-id", access_token="token")

    def test_environment_is_a_connection_host_field(self) -> None:
        # `environment` decides which host receives the stored token; changing it must force
        # the editor to re-enter the token or the credential could be exfiltrated.
        assert self.source.connection_host_fields == ["environment"]

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
        ],
    )
    def test_validate_credentials(self, status: int, expected_valid: bool, expected_message: str | None) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert len(network.requests_log) == 1
        request = network.requests_log[0]
        assert request.path == "/api/v2/agents"
        assert request.origin == "https://services.babelforce.com"
        assert request.headers["x-auth-access-id"] == self.config.access_id
        assert request.headers["x-auth-access-token"] == self.config.access_token

    def test_validate_credentials_rejects_bad_environment_without_probing(self) -> None:
        config = BabelforceSourceConfig(environment="evil.example.com", access_id="id", access_token="token")

        with scripted_network([]) as network:
            is_valid, error_message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error_message is not None
        assert network.requests_log == []
