import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.xendit import XenditSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.xendit.settings import XENDIT_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.xendit.source import XenditSource

VALIDATE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.xendit.source.validate_xendit_credentials"
)
SOURCE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.xendit.source.xendit_source"


class TestXenditSource:
    def setup_method(self):
        self.source = XenditSource()
        self.team_id = 123
        self.config = XenditSourceConfig(api_key="xnd_test_key")

    @pytest.mark.parametrize(
        "status, schema_name, expected_valid, expected_message",
        [
            (200, None, True, None),
            (200, "transactions", True, None),
            # A key without a table's permission is still a real key, so source creation succeeds
            # and only the per-table check rejects it.
            (403, None, True, None),
            (403, "accounts", False, "Your Xendit API key is missing the Accounts Read permission"),
            (401, None, False, "Invalid Xendit API key"),
            (None, None, False, "Invalid Xendit API key"),
        ],
    )
    @mock.patch(VALIDATE_PATCH)
    def test_validate_credentials(self, mock_validate, status, schema_name, expected_valid, expected_message):
        mock_validate.return_value = (status == 200, status)

        is_valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)

        assert (is_valid, message) == (expected_valid, expected_message)

    @mock.patch(VALIDATE_PATCH)
    def test_validate_credentials_probes_the_requested_table(self, mock_validate):
        mock_validate.return_value = (True, 200)

        self.source.validate_credentials(self.config, self.team_id, schema_name="accounts")

        assert mock_validate.call_args.args[1] == XENDIT_ENDPOINTS["accounts"].path

    @pytest.mark.parametrize(
        "status, expected",
        [
            (200, None),
            (403, "Your Xendit API key is missing the Transaction Read permission"),
            # A throttle or a blip is not a permission problem, so the table stays selectable.
            (429, None),
            (None, None),
        ],
    )
    @mock.patch(VALIDATE_PATCH)
    def test_get_endpoint_permissions(self, mock_validate, status, expected):
        mock_validate.return_value = (status == 200, status)

        permissions = self.source.get_endpoint_permissions(self.config, self.team_id, ["transactions"])

        assert permissions == {"transactions": expected}

    @mock.patch(VALIDATE_PATCH)
    def test_get_endpoint_permissions_ignores_unknown_tables(self, mock_validate):
        assert self.source.get_endpoint_permissions(self.config, self.team_id, ["nonexistent"]) == {"nonexistent": None}
        mock_validate.assert_not_called()
