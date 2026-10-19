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

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["flags"])
        assert len(schemas) == 1
        assert schemas[0].name == "flags"

    @pytest.mark.parametrize(
        "status, schema_name, expected_valid",
        [
            (200, None, True),
            (401, None, False),
            # A valid token may lack scope for an unselected endpoint — accept 403 at source-create.
            (403, None, True),
            # But reject 403 when validating a specific schema.
            (403, "flags", False),
            (500, None, False),
            (None, None, False),
        ],
    )
    def test_validate_credentials_status_mapping(
        self, status: int | None, schema_name: str | None, expected_valid: bool
    ) -> None:
        answer = ConnectionError("unreachable") if status is None else ScriptedResponse(status=status)
        with scripted_network(always(answer)) as network:
            is_valid, _error = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)

        assert is_valid is expected_valid
        assert {request.path for request in network.requests_log} == {
            "/api/v2/projects" if schema_name == "flags" else "/api/v2/caller-identity"
        }
