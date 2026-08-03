from unittest import mock

from posthog.schema import ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.shipmail import (
    ShipmailSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shipmail.source import ShipmailSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

CAPABILITIES_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.shipmail.source.get_capabilities"


class TestShipmailSource:
    def setup_method(self) -> None:
        self.source = ShipmailSource()
        self.config = ShipmailSourceConfig(api_key="test-key")

    def test_source_metadata(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.SHIPMAIL
        assert self.source.lists_tables_without_credentials is True
        assert self.source.get_source_config.releaseStatus == ReleaseStatus.ALPHA

    def test_static_schemas_include_keys_and_incremental_support(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, team_id=1)}

        assert set(schemas) == {"messages", "mailboxes", "domains", "suppressions"}
        assert schemas["messages"].supports_incremental is True
        assert schemas["messages"].detected_primary_keys == ["id"]
        assert schemas["mailboxes"].supports_incremental is False
        assert schemas["suppressions"].detected_primary_keys == ["email_address"]

    def test_schema_filter(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["domains"])
        assert [schema.name for schema in schemas] == ["domains"]

    def test_documented_tables_are_available_without_credentials(self) -> None:
        tables = {table["name"]: table for table in self.source.get_documented_tables()}

        assert set(tables) == {"messages", "mailboxes", "domains", "suppressions"}
        assert tables["messages"]["sync_methods"] == ["Incremental", "Full refresh"]
        assert tables["messages"]["incremental_fields"] == ["updated_at"]
        assert tables["messages"]["primary_keys"] == ["id"]
        assert tables["suppressions"]["primary_keys"] == ["email_address"]

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
