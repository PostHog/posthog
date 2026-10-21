from products.warehouse_sources.backend.temporal.data_imports.sources.bluetally.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bluetally.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.bluetally.source import BluetallySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bluetally import (
    BluetallySourceConfig,
)


def _config(api_key: str = "key", tenant_id: str | None = None) -> BluetallySourceConfig:
    return BluetallySourceConfig(api_key=api_key, tenant_id=tenant_id)


class TestSourceConfig:
    def test_connection_host_fields_force_secret_reentry_on_tenant_change(self) -> None:
        # Changing tenant_id retargets the stored API key, so it must count as a host field.
        assert BluetallySource().connection_host_fields == ["tenant_id"]


class TestValidateCredentials:
    def test_failure(self) -> None:
        with scripted_network([ScriptedResponse(status=401)]):
            ok, error = BluetallySource().validate_credentials(_config(), team_id=1)
        assert ok is False
        assert error is not None

    def test_probes_specific_endpoint_path(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            BluetallySource().validate_credentials(_config(), team_id=1, schema_name="employees")
        assert len(network.requests_log) == 1
        assert network.requests_log[0].path == "/api/v1/employees"
        assert network.requests_log[0].headers["authorization"] == "Bearer key"
        assert network.requests_log[0].param("tenant_id") is None


class TestCanonicalDescriptions:
    def test_canonical_descriptions_keys_are_known_endpoints(self) -> None:
        # Every documented table must map to a real endpoint, or its descriptions never apply.
        assert set(CANONICAL_DESCRIPTIONS).issubset(set(ENDPOINTS))
