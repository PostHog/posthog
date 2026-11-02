import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.appsignal.source import AppsignalSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appsignal import (
    AppsignalSourceConfig,
)


class TestAppsignalSource:
    def setup_method(self):
        self.source = AppsignalSource()
        self.team_id = 123
        self.config = AppsignalSourceConfig(api_token="api-token", app_id="app-id")

    def test_connection_host_fields_force_secret_reentry_on_app_change(self):
        # Changing app_id retargets the stored token at a different AppSignal app, so the update
        # serializer must require re-entering the secret — regressing this reopens that hole.
        assert self.source.connection_host_fields == ["app_id"]

    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_message",
        [
            (200, True, None),
        ],
    )
    def test_validate_credentials(self, status_code: int, expected_valid: bool, expected_message: str | None) -> None:
        with scripted_network([ScriptedResponse(status=status_code, json={})]) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert network.requests_log[0].path == "/api/app-id/markers.json"
        assert network.requests_log[0].param("token") == self.config.api_token
