import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.aha_ideas.source import AhaIdeasSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ahaideas import (
    AhaIdeasSourceConfig,
)


class TestAhaIdeasSource:
    def setup_method(self) -> None:
        self.source = AhaIdeasSource()
        self.team_id = 123
        self.config = AhaIdeasSourceConfig(subdomain="acme", api_key="key")

    def test_subdomain_listed_as_connection_host_field(self) -> None:
        # The API key is sent to <subdomain>.aha.io, so retargeting the subdomain must re-require it.
        assert self.source.connection_host_fields == ["subdomain"]

    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_message",
        [
            (None, False, "Could not connect to Aha! with the provided account domain and API key"),
        ],
    )
    def test_validate_credentials(
        self, status_code: int | None, expected_valid: bool, expected_message: str | None
    ) -> None:
        script = [ConnectionResetError("reset")] if status_code is None else [ScriptedResponse(status=status_code)]
        with scripted_network(script) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert network.requests_log
        assert all(request.path == "/api/v1/me" for request in network.requests_log)
        assert all(request.headers["authorization"] == "Bearer key" for request in network.requests_log)

    def test_validate_credentials_surfaces_bad_subdomain(self) -> None:
        self.config = AhaIdeasSourceConfig(subdomain="a/b", api_key="key")
        with scripted_network([]) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert "Invalid Aha! account domain" in (error_message or "")
        assert network.requests_log == []
