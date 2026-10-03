from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.orb import OrbSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.orb.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.orb.source import OrbSource


def _config() -> OrbSourceConfig:
    return OrbSourceConfig(api_key="orb-key")

    # Shipped behind the unreleased flag while in alpha.


class TestGetSchemas:
    def test_returns_all_endpoints(self) -> None:
        schemas = OrbSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @parameterized.expand(list(ENDPOINTS))
    def test_incremental_support_matches_settings(self, endpoint: str) -> None:
        schema = next(s for s in OrbSource().get_schemas(_config(), team_id=1) if s.name == endpoint)
        expected = endpoint in INCREMENTAL_FIELDS
        assert schema.supports_incremental is expected
        assert schema.supports_append is expected
        if expected:
            assert schema.incremental_fields == INCREMENTAL_FIELDS[endpoint]

    def test_names_filter(self) -> None:
        schemas = OrbSource().get_schemas(_config(), team_id=1, names=["Customers", "Coupons"])
        assert {s.name for s in schemas} == {"Customers", "Coupons"}


class TestValidateCredentials:
    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.orb.source.validate_orb_credentials")
    def test_validate(self, _label: str, api_result: bool, expected_ok: bool, mock_validate: MagicMock) -> None:
        mock_validate.return_value = api_result
        ok, error = OrbSource().validate_credentials(_config(), team_id=1)
        assert ok is expected_ok
        assert (error is None) is expected_ok


class TestSourceWiring:
    def test_canonical_descriptions_present(self) -> None:
        descriptions = OrbSource().get_canonical_descriptions()
        # Keyed by schema name; every documented key must be a real endpoint.
        assert "Customers" in descriptions
        assert set(descriptions.keys()).issubset(set(ENDPOINTS))
