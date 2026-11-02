import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.codecov.source import CodecovSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.codecov import (
    CodecovSourceConfig,
)


class TestCodecovSource:
    def setup_method(self):
        self.source = CodecovSource()
        self.team_id = 123
        self.config = CodecovSourceConfig(owner_username="acme", api_token="token")

    def test_connection_host_fields_force_secret_reentry_on_scope_change(self):
        # Retargeting the git provider, owner, or repository allow-list reuses the stored token
        # against different Codecov resources, so the update serializer must require re-entry.
        assert self.source.connection_host_fields == ["service", "owner_username", "repositories"]

    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_message",
        [
            (404, False, "Owner 'acme' not found on Codecov for the selected git provider"),
            (None, False, "Could not connect to Codecov with the provided credentials"),
        ],
    )
    def test_validate_credentials(
        self, status_code: int | None, expected_valid: bool, expected_message: str | None
    ) -> None:
        answer = ScriptedResponse(status=status_code) if status_code is not None else requests.ConnectionError("boom")
        with scripted_network([answer]) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert network.requests_log
        assert {request.url for request in network.requests_log} == {
            "https://api.codecov.io/api/v2/github/acme/repos?page_size=1"
        }
