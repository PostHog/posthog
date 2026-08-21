import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.twilio import (
    TwilioAuthMethodConfig,
    TwilioSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.twilio.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.twilio.source import TwilioSource
from products.warehouse_sources.backend.temporal.data_imports.sources.twilio.twilio import (
    TWILIO_MAIN_KEY_REQUIRED_REASON,
)

ACCOUNT_SID = "AC00000000000000000000000000000000"
TWILIO_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.twilio.twilio.make_tracked_session"
)


def _api_key_config():
    return TwilioSourceConfig(
        account_sid=ACCOUNT_SID,
        auth_method=TwilioAuthMethodConfig(selection="api_key", api_key_sid="SK123", api_key_secret="secret"),
    )


def _auth_token_config():
    return TwilioSourceConfig(
        account_sid=ACCOUNT_SID,
        auth_method=TwilioAuthMethodConfig(selection="auth_token", auth_token="token"),
    )


class TestTwilioSource:
    def setup_method(self):
        self.source = TwilioSource()
        self.team_id = 123
        self.config = _api_key_config()

    def test_main_key_only_tables_default_off(self):
        # One-shot setup builds its schema list straight from get_schemas and never calls
        # get_endpoint_permissions, so without this the `keys` table is enabled for a Standard API
        # key and its first sync fails non-retryably.
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["keys"].should_sync_default is False
        assert all(s.should_sync_default for name, s in schemas.items() if name != "keys")

    @pytest.mark.parametrize(
        "config_factory, expected_auth",
        [
            (_api_key_config, ("SK123", "secret")),
            (_auth_token_config, (ACCOUNT_SID, "token")),
        ],
    )
    def test_get_auth_resolves_basic_auth(self, config_factory, expected_auth):
        assert self.source._get_auth(config_factory()) == expected_auth

    @pytest.mark.parametrize(
        "config",
        [
            TwilioSourceConfig(account_sid=ACCOUNT_SID, auth_method=TwilioAuthMethodConfig(selection="auth_token")),
            TwilioSourceConfig(account_sid=ACCOUNT_SID, auth_method=TwilioAuthMethodConfig(selection="api_key")),
        ],
    )
    def test_validate_credentials_missing_secrets(self, config):
        is_valid, error = self.source.validate_credentials(config, self.team_id)
        assert is_valid is False
        assert error is not None

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.twilio.source.validate_twilio_credentials"
    )
    def test_validate_credentials_delegates(self, mock_validate):
        mock_validate.return_value = (True, None)
        is_valid, error = self.source.validate_credentials(self.config, self.team_id, schema_name="messages")
        assert is_valid is True
        assert error is None
        mock_validate.assert_called_once_with(("SK123", "secret"), ACCOUNT_SID, "messages")

    @pytest.mark.parametrize(
        "status_code, expected_keys_reason",
        [
            (401, TWILIO_MAIN_KEY_REQUIRED_REASON),
            (403, TWILIO_MAIN_KEY_REQUIRED_REASON),
            (200, None),
            # A throttle or a server error must not hide a table the credential can actually read.
            (429, None),
            (500, None),
        ],
    )
    @mock.patch(TWILIO_SESSION_PATCH)
    def test_get_endpoint_permissions_gates_only_the_keys_table(self, mock_session, status_code, expected_keys_reason):
        getter = mock_session.return_value.get
        getter.return_value = mock.MagicMock(status_code=status_code)

        result = self.source.get_endpoint_permissions(self.config, self.team_id, list(ENDPOINTS))

        assert result["keys"] == expected_keys_reason
        assert {name: reason for name, reason in result.items() if name != "keys"} == dict.fromkeys(
            name for name in ENDPOINTS if name != "keys"
        )
        # Probing every table would add a round-trip per table to an interactive request.
        assert getter.call_count == 1

    @mock.patch(TWILIO_SESSION_PATCH)
    def test_get_endpoint_permissions_survives_missing_secrets(self, mock_session):
        config = TwilioSourceConfig(account_sid=ACCOUNT_SID, auth_method=TwilioAuthMethodConfig(selection="api_key"))

        result = self.source.get_endpoint_permissions(config, self.team_id, list(ENDPOINTS))

        assert result == dict.fromkeys(ENDPOINTS)
        mock_session.assert_not_called()
