import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.opsgenie import (
    OpsgenieSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opsgenie.source import OpsgenieSource


class TestOpsgenieSource:
    def setup_method(self) -> None:
        self.source = OpsgenieSource()
        self.config = OpsgenieSourceConfig(api_key="key_123", region="us")

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["alerts", "users"])
        assert {s.name for s in schemas} == {"alerts", "users"}

    def test_validate_credentials_success(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert self.source.validate_credentials(self.config, team_id=1) == (True, None)
        assert network.requests_log[0].path == "/v2/users"

    @pytest.mark.parametrize(
        "status,error",
        [
            (401, "Invalid Opsgenie API key"),
            (422, "Your Opsgenie API key format is not valid"),
        ],
    )
    def test_validate_credentials_invalid_key(self, status: int, error: str) -> None:
        with scripted_network([ScriptedResponse(status=status)]):
            ok, returned_error = self.source.validate_credentials(self.config, team_id=1)
        assert ok is False
        assert returned_error == error

    def test_validate_credentials_accepts_403_at_source_create(self) -> None:
        # A valid key may only have access to a subset of resources (e.g. no Configuration
        # access for integrations); don't block connection.
        with scripted_network([ScriptedResponse(status=403)]):
            assert self.source.validate_credentials(self.config, team_id=1, schema_name=None) == (True, None)

    def test_validate_credentials_rejects_403_for_specific_schema(self) -> None:
        with scripted_network([ScriptedResponse(status=403)]) as network:
            ok, error = self.source.validate_credentials(self.config, team_id=1, schema_name="integrations")
        assert ok is False
        assert error == "Your Opsgenie API key does not have access to this resource"
        assert network.requests_log[0].path == "/v2/integrations"
