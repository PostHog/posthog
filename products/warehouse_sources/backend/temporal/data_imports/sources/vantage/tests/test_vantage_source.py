from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.facade.source_config import SourceFieldInputConfig, SourceFieldInputConfigType
from products.warehouse_sources.backend.temporal.data_imports.sources.vantage.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.vantage.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.vantage.source import VantageSource


class TestVantageSourceConfig:
    def test_config_has_single_secret_api_key_field(self) -> None:
        # The token is a credential; a non-secret/non-password field would leak it in the UI and API.
        config = VantageSource().get_source_config
        fields = config.fields
        assert len(fields) == 1
        field = fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "api_key"
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.required is True
        assert field.secret is True


class TestValidateCredentials:
    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_delegates_to_transport(self, _name: str, transport_result: bool, expected_ok: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.vantage.source.validate_vantage_credentials",
            return_value=transport_result,
        ):
            ok, error = VantageSource().validate_credentials(MagicMock(), team_id=1)
        assert ok is expected_ok
        assert (error is None) is expected_ok


class TestResumableWiring:
    def test_source_for_pipeline_plumbs_schema_name(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "cost_reports"
        config = MagicMock()
        config.api_key = "tok"
        response = VantageSource().source_for_pipeline(config, MagicMock(), inputs)
        assert response.name == "cost_reports"
        assert response.primary_keys == ["token"]


class TestPublicDocsCatalog:
    def test_canonical_description_keys_are_real_endpoints(self) -> None:
        # A key that doesn't match an endpoint name would silently never apply to any synced table.
        assert set(CANONICAL_DESCRIPTIONS).issubset(set(ENDPOINTS))


class TestSchemaDefaults:
    def test_fan_out_tables_are_off_by_default(self) -> None:
        schemas = {schema.name: schema for schema in VantageSource().get_schemas(MagicMock(), team_id=1)}
        off_by_default = {"costs", "resources", "tag_values"}
        assert {name for name, schema in schemas.items() if not schema.should_sync_default} == off_by_default
