from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.shipmail import (
    ShipmailSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shipmail.source import ShipmailSource

CAPABILITIES_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.shipmail.source.get_capabilities"


class TestShipmailSource:
    def setup_method(self) -> None:
        self.source = ShipmailSource()
        self.config = ShipmailSourceConfig(api_key="test-key")

    def test_schema_filter(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["domains"])
        assert [schema.name for schema in schemas] == ["domains"]

    @mock.patch(CAPABILITIES_PATCH, return_value=(200, {"messages:read"}))
    def test_validates_token_without_requiring_every_table_scope(self, get_capabilities: mock.MagicMock) -> None:
        assert self.source.validate_credentials(self.config, team_id=1) == (True, None)
        assert self.source.validate_credentials(self.config, team_id=1, schema_name="messages") == (True, None)
        assert self.source.validate_credentials(self.config, team_id=1, schema_name="domains") == (
            False,
            "Your Shipmail API key is missing the `domains:read` scope",
        )

    @mock.patch(CAPABILITIES_PATCH, return_value=(200, {"messages:read", "suppressions:read"}))
    def test_endpoint_permissions_use_one_capabilities_response(self, get_capabilities: mock.MagicMock) -> None:
        permissions = self.source.get_endpoint_permissions(
            self.config,
            team_id=1,
            endpoints=["messages", "mailboxes", "suppressions"],
        )

        assert permissions == {
            "messages": None,
            "mailboxes": "API key is missing the `mailboxes:read` scope",
            "suppressions": None,
        }
        get_capabilities.assert_called_once_with("test-key")

    @mock.patch(CAPABILITIES_PATCH, return_value=(401, set()))
    def test_rejects_invalid_token(self, get_capabilities: mock.MagicMock) -> None:
        assert self.source.validate_credentials(self.config, team_id=1) == (False, "Invalid Shipmail API key")
