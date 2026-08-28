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

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.twilio.com/2010-04-01/Accounts/AC1/Messages.json",
            "403 Client Error: Forbidden for url: https://api.twilio.com/2010-04-01/Accounts/AC1/Calls.json",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.twilio.com/2010-04-01/Accounts/AC1/Messages.json",
        ],
    )
    def test_non_retryable_errors_ignore_unrelated(self, other_error):
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

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

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.twilio.source.twilio_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_twilio_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "messages"
        inputs.team_id = 123
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-03-04"
        inputs.incremental_field = "date_sent"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_twilio_source.call_args.kwargs
        assert kwargs["auth"] == ("SK123", "secret")
        assert kwargs["account_sid"] == ACCOUNT_SID
        assert kwargs["endpoint"] == "messages"
        assert kwargs["team_id"] == 123
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-03-04"
        assert kwargs["incremental_field"] == "date_sent"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.twilio.source.twilio_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_twilio_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "addresses"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-03-04"
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_twilio_source.call_args.kwargs["db_incremental_field_last_value"] is None
