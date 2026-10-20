from typing import Optional

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.awin.source import AwinSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awin import AwinSourceConfig


class TestAwinSourceClass:
    def test_config_without_region_defaults_for_pre_existing_connections(self) -> None:
        # Connections configured before this field existed have no `region` key in their stored
        # config. It must default rather than fail to parse, or every endpoint for those
        # connections (not just reports_advertiser) would break.
        assert AwinSourceConfig(api_token="x").region == "GB"

    @parameterized.expand(
        [
            ("transactions", True),
            ("accounts", False),
            ("programmes", False),
            ("programme_details", False),
            ("commission_groups", False),
            ("reports_advertiser", False),
            ("reports_publisher", False),
            ("advertiser_publishers", False),
        ]
    )
    def test_supports_incremental_per_endpoint(self, endpoint: str, expected: bool) -> None:
        schemas = AwinSource().get_schemas(AwinSourceConfig(api_token="x"), team_id=1, names=[endpoint])
        assert len(schemas) == 1
        assert schemas[0].supports_incremental is expected

    @parameterized.expand([("valid", True, True, None), ("invalid", False, False, "Invalid Awin API token")])
    def test_validate_credentials(self, _name: str, api_result: bool, ok: bool, err: Optional[str]) -> None:
        with scripted_network([ScriptedResponse(status=200 if api_result else 401)]) as network:
            result = AwinSource().validate_credentials(AwinSourceConfig(api_token="x"), team_id=1)
        assert result == (ok, err)
        assert [request.path for request in network.requests_log] == ["/accounts"]
