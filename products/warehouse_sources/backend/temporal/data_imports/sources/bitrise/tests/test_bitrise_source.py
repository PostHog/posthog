import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.bitrise.source import BitriseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bitrise import (
    BitriseSourceConfig,
)


class TestBitriseSource:
    def setup_method(self) -> None:
        self.source = BitriseSource()
        self.team_id = 123
        self.config = BitriseSourceConfig(api_token="bitrise-token")

    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_message",
        [
            (200, True, None),
        ],
    )
    def test_validate_credentials(self, status_code: int, expected_valid: bool, expected_message: str | None) -> None:
        answers = [ScriptedResponse(status=status_code, json={"data": {}})]
        if status_code != 200:
            answers.append(ScriptedResponse(status=status_code, json={"data": {}}))
        with scripted_network(answers) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert [request.path for request in network.requests_log] == (
            ["/v0.1/me"] if status_code == 200 else ["/v0.1/me", "/v0.1/apps"]
        )
        assert all(request.headers["authorization"] == self.config.api_token for request in network.requests_log)
