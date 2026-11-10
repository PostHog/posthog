import pytest
from unittest import mock

from products.warehouse_sources.sources.shipmail._config import ShipmailSourceConfig
from products.warehouse_sources.sources.shipmail.source import ShipmailSource

CAPABILITIES_PATCH = "products.warehouse_sources.sources.shipmail.source.get_capabilities"


class TestShipmailSource:
    def setup_method(self) -> None:
        self.source = ShipmailSource()
        self.config = ShipmailSourceConfig(api_key="test-key")

    @pytest.mark.parametrize(
        "scopes,expected",
        [
            ({"threads:read"}, (False, "Your Shipmail API key is missing the `mailboxes:read` scope")),
            ({"mailboxes:read"}, (False, "Your Shipmail API key is missing the `threads:read` scope")),
            ({"threads:read", "mailboxes:read"}, (True, None)),
            ({"*"}, (True, None)),
        ],
    )
    @mock.patch(CAPABILITIES_PATCH)
    def test_validates_token_without_requiring_every_table_scope(
        self, get_capabilities: mock.MagicMock, scopes: set[str], expected: tuple[bool, str | None]
    ) -> None:
        get_capabilities.return_value = (200, scopes)
        assert self.source.validate_credentials(self.config, team_id=1) == (True, None)
        assert self.source.validate_credentials(self.config, team_id=1, schema_name="threads") == expected

    @mock.patch(
        CAPABILITIES_PATCH, return_value=(200, {"messages:read", "suppressions:read", "threads:read", "audiences:read"})
    )
    def test_endpoint_permissions_use_one_capabilities_response(self, get_capabilities: mock.MagicMock) -> None:
        permissions = self.source.get_endpoint_permissions(
            self.config,
            team_id=1,
            endpoints=[
                "messages",
                "mailboxes",
                "suppressions",
                "threads",
                "audience_subscribers",
                "newsletters",
                "members",
            ],
        )

        assert permissions == {
            "messages": None,
            "mailboxes": "API key is missing the `mailboxes:read` scope",
            "suppressions": None,
            "threads": "API key is missing the `mailboxes:read` scope",
            "audience_subscribers": None,
            "newsletters": "API key is missing the `newsletters:read` scope",
            "members": "API key is missing the `members:read` scope",
        }
        get_capabilities.assert_called_once_with("test-key")

    @mock.patch(CAPABILITIES_PATCH, return_value=(401, set()))
    def test_rejects_invalid_token(self, get_capabilities: mock.MagicMock) -> None:
        assert self.source.validate_credentials(self.config, team_id=1) == (False, "Invalid Shipmail API key")
