import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.launchdarkly import (
    LaunchDarklySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.source import LaunchDarklySource


class TestLaunchDarklySource:
    def setup_method(self):
        self.source = LaunchDarklySource()
        self.team_id = 123
        self.config = LaunchDarklySourceConfig(access_token="api-token")

    @pytest.mark.parametrize(
        "status, schema_name, expected_valid, expected_probe",
        [
            (200, None, True, "/api/v2/caller-identity"),
            (401, None, False, "/api/v2/caller-identity"),
            # A valid token may lack scope for an unselected endpoint — accept 403 at source-create.
            (403, None, True, "/api/v2/caller-identity"),
            # But reject 403 when validating a specific schema.
            (403, "flags", False, "/api/v2/projects"),
            (403, "team_roles", False, "/api/v2/teams"),
            (200, "team_maintainers", True, "/api/v2/teams"),
            (200, "code_ref_repositories", True, "/api/v2/code-refs/repositories"),
            (500, None, False, "/api/v2/caller-identity"),
            (None, None, False, "/api/v2/caller-identity"),
        ],
    )
    def test_validate_credentials_status_mapping(
        self, status: int | None, schema_name: str | None, expected_valid: bool, expected_probe: str
    ) -> None:
        answer = ConnectionError("unreachable") if status is None else ScriptedResponse(status=status)
        with scripted_network(always(answer)) as network:
            is_valid, _error = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)

        assert is_valid is expected_valid
        assert {request.path for request in network.requests_log} == {expected_probe}
