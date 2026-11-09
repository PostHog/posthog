from products.warehouse_sources.sources.hubplanner._config import HubplannerSourceConfig
from products.warehouse_sources.sources.hubplanner.source import HubplannerSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, scripted_network


class TestHubplannerSource:
    def setup_method(self) -> None:
        self.source = HubplannerSource()
        self.team_id = 123

    def test_validate_credentials_success(self) -> None:
        config = HubplannerSourceConfig(api_key="good")
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert self.source.validate_credentials(config, self.team_id) == (True, None)
        assert network.requests_log[0].headers["authorization"] == "good"

    def test_validate_credentials_failure(self) -> None:
        config = HubplannerSourceConfig(api_key="bad")
        with scripted_network([ScriptedResponse(status=403)]) as network:
            valid, error = self.source.validate_credentials(config, self.team_id)
        assert valid is False
        assert error is not None
        assert network.requests_log[0].headers["authorization"] == "bad"
