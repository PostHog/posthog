from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.omni import OmniSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.omni.source import OmniSource


class TestOmniSource:
    def setup_method(self):
        self.source = OmniSource()
        self.team_id = 123
        self.config = OmniSourceConfig(host="https://acme.omniapp.co", api_key="omni-key")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.omni.source.get_omni_endpoint_permissions"
    )
    def test_get_endpoint_permissions_delegates(self, mock_get_permissions):
        mock_get_permissions.return_value = {"Users": "some reason", "Documents": None}

        result = self.source.get_endpoint_permissions(self.config, self.team_id, ["Users", "Documents"])

        assert result == {"Users": "some reason", "Documents": None}
        mock_get_permissions.assert_called_once_with(self.config.host, self.config.api_key, ["Users", "Documents"])
