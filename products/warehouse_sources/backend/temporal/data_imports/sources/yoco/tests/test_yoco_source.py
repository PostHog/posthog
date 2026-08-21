from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.yoco import YocoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.yoco.source import YocoSource


class TestYocoSource:
    def setup_method(self) -> None:
        self.source = YocoSource()
        self.team_id = 123
        self.config = YocoSourceConfig(api_key="yoco-key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.yoco.source.api_client")
    def test_get_endpoint_permissions_plumbs_endpoints(self, mock_client: mock.MagicMock) -> None:
        mock_client.get_endpoint_permissions.return_value = {"payments": None}
        assert self.source.get_endpoint_permissions(self.config, self.team_id, ["payments"]) == {"payments": None}
        assert mock_client.get_endpoint_permissions.call_args.args == ("yoco-key", ["payments"])
