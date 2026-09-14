import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.xendit import XenditSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.xendit.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.xendit.settings import ENDPOINTS, XENDIT_ENDPOINTS
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

    def test_connection_host_fields_pin_sub_account(self):
        # Retargeting the stored key at another sub-account must force credential re-entry.
        assert self.source.connection_host_fields == ["sub_account_user_id"]

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Xendit"
        assert config.label == "Xendit"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source ships visible: unreleasedSource hides it from users entirely.
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/xendit.png"

        fields = {field.name: field for field in config.fields if isinstance(field, SourceFieldInputConfig)}
        assert set(fields) == {"api_key", "sub_account_user_id"}
        assert fields["api_key"].type == SourceFieldInputConfigType.PASSWORD
        assert fields["api_key"].required is True
        assert fields["api_key"].secret is True
        # The sub-account id is a xenPlatform-only routing hint, not a credential.
        assert fields["sub_account_user_id"].required is False
        assert fields["sub_account_user_id"].secret is False

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.xendit.co/transactions?limit=50",
            "403 Client Error: Forbidden for url: https://api.xendit.co/v2/accounts?limit=50",
        ],
    )
    def test_auth_failures_are_non_retryable(self, observed_error):
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    def test_sub_account_table_is_not_synced_by_default(self):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["transactions"].should_sync_default is True
        # Sub-accounts only exist for xenPlatform merchants, so selecting it is opt-in.
        assert schemas["accounts"].should_sync_default is False

    def test_canonical_descriptions_cover_every_endpoint(self):
        assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)

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
