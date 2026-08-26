from typing import Optional

from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.awin import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.awin.source import AwinSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awin import AwinSourceConfig


class TestAwinSourceClass:
    def test_get_source_config_region_field(self) -> None:
        # Awin's aggregated advertiser report 400s without a region (no "all regions" value exists),
        # so every connection must pick one.
        region_field = AwinSource().get_source_config.fields[1]
        assert isinstance(region_field, SourceFieldSelectConfig)
        assert region_field.name == "region"
        assert region_field.required is True
        assert region_field.defaultValue == "GB"
        assert {option.value for option in region_field.options} >= {"GB", "US", "DE"}

    def test_lists_tables_without_credentials(self) -> None:
        assert AwinSource.lists_tables_without_credentials is True

    def test_config_without_region_defaults_for_pre_existing_connections(self) -> None:
        # Connections configured before this field existed have no `region` key in their stored
        # config. It must default rather than fail to parse, or every endpoint for those
        # connections (not just reports_advertiser) would break.
        assert AwinSourceConfig(api_token="x").region == "GB"

    def test_get_schemas_returns_all_endpoints(self) -> None:
        schemas = AwinSource().get_schemas(AwinSourceConfig(api_token="x"), team_id=1)
        names = {s.name for s in schemas}
        assert names == {"accounts", "programmes", "transactions", "reports_advertiser"}

    @parameterized.expand(
        [
            ("transactions", True),
            ("accounts", False),
            ("programmes", False),
            ("reports_advertiser", False),
        ]
    )
    def test_supports_incremental_per_endpoint(self, endpoint: str, expected: bool) -> None:
        schemas = AwinSource().get_schemas(AwinSourceConfig(api_token="x"), team_id=1, names=[endpoint])
        assert len(schemas) == 1
        assert schemas[0].supports_incremental is expected

    def test_transactions_advertises_both_date_fields(self) -> None:
        schemas = AwinSource().get_schemas(AwinSourceConfig(api_token="x"), team_id=1, names=["transactions"])
        fields = {f["field"] for f in schemas[0].incremental_fields}
        assert fields == {"transactionDate", "validationDate"}

    def test_documented_tables_render_without_credentials(self) -> None:
        tables = AwinSource().get_documented_tables()
        names = {t["name"] for t in tables}
        assert names == {"accounts", "programmes", "transactions", "reports_advertiser"}

    @parameterized.expand([("valid", True, True, None), ("invalid", False, False, "Invalid Awin API token")])
    def test_validate_credentials(self, _name: str, api_result: bool, ok: bool, err: Optional[str]) -> None:
        with patch.object(source_module, "validate_awin_credentials", return_value=api_result):
            result = AwinSource().validate_credentials(AwinSourceConfig(api_token="x"), team_id=1)
        assert result == (ok, err)
