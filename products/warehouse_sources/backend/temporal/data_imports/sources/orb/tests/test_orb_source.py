from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.orb import OrbSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.orb.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.orb.source import OrbSource


def _config() -> OrbSourceConfig:
    return OrbSourceConfig(api_key="orb-key")

    # Shipped behind the unreleased flag while in alpha.


class TestGetSchemas:
    @parameterized.expand(list(ENDPOINTS))
    def test_incremental_support_matches_settings(self, endpoint: str) -> None:
        schema = next(s for s in OrbSource().get_schemas(_config(), team_id=1) if s.name == endpoint)
        expected = endpoint in INCREMENTAL_FIELDS
        assert schema.supports_incremental is expected
        assert schema.supports_append is expected
        if expected:
            assert schema.incremental_fields == INCREMENTAL_FIELDS[endpoint]


class TestValidateCredentials:
    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_validate(self, _label: str, api_result: bool, expected_ok: bool) -> None:
        status_code = 200 if api_result else 401
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            ok, error = OrbSource().validate_credentials(_config(), team_id=1)

        assert ok is expected_ok
        assert (error is None) is expected_ok
        assert network.requests_log[0].path == "/v1/customers"


class TestSourceWiring:
    def test_canonical_descriptions_present(self) -> None:
        descriptions = OrbSource().get_canonical_descriptions()
        # Keyed by schema name; every documented key must be a real endpoint.
        assert "Customers" in descriptions
        assert set(descriptions.keys()).issubset(set(ENDPOINTS))
