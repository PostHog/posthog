from unittest.mock import patch

from sources.hubplanner import source as source_module
from sources.hubplanner._config import HubplannerSourceConfig
from sources.hubplanner.source import HubplannerSource


class TestHubplannerSource:
    def setup_method(self) -> None:
        self.source = HubplannerSource()
        self.team_id = 123

    def test_validate_credentials_success(self) -> None:
        config = HubplannerSourceConfig(api_key="good")
        with patch.object(source_module, "validate_hubplanner_credentials", return_value=True):
            assert self.source.validate_credentials(config, self.team_id) == (True, None)

    def test_validate_credentials_failure(self) -> None:
        config = HubplannerSourceConfig(api_key="bad")
        with patch.object(source_module, "validate_hubplanner_credentials", return_value=False):
            valid, error = self.source.validate_credentials(config, self.team_id)
        assert valid is False
        assert error is not None
