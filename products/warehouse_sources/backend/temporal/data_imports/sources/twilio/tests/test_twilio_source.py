import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    TwilioAuthMethodConfig,
    TwilioSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.twilio.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.twilio.source import TwilioSource
from products.warehouse_sources.backend.temporal.data_imports.sources.twilio.twilio import TwilioResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

ACCOUNT_SID = "AC00000000000000000000000000000000"


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

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.TWILIO

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Twilio"
        assert config.label == "Twilio"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/twilio.png"

        field_names = [f.name for f in config.fields]
        assert field_names == ["account_sid", "auth_method"]

    def test_auth_method_offers_both_credential_types(self):
        config = self.source.get_source_config
        auth_field = next(f for f in config.fields if isinstance(f, SourceFieldSelectConfig))
        assert {o.value for o in auth_field.options} == {"api_key", "auth_token"}

    def test_secret_fields_are_passwords(self):
        config = self.source.get_source_config
        secrets = {
            f.name
            for option_field in config.fields
            if isinstance(option_field, SourceFieldSelectConfig)
            for o in option_field.options
            for f in (o.fields or [])
            if isinstance(f, SourceFieldInputConfig) and f.type == SourceFieldInputConfigType.PASSWORD
        }
        assert secrets == {"api_key_secret", "auth_token"}

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

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        incremental = {s.name for s in schemas if s.supports_incremental}
        assert incremental == {"messages", "calls", "recordings", "conferences"}

    def test_incremental_schemas_advertise_their_fields(self):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["messages"].incremental_fields == INCREMENTAL_FIELDS["messages"]
        assert schemas["addresses"].incremental_fields == []
        assert schemas["addresses"].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["calls"])
        assert [s.name for s in schemas] == ["calls"]

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

    def test_get_resumable_source_manager_binds_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is TwilioResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.twilio.source.twilio_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_twilio_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "messages"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-03-04"
        inputs.incremental_field = "date_sent"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_twilio_source.call_args.kwargs
        assert kwargs["auth"] == ("SK123", "secret")
        assert kwargs["account_sid"] == ACCOUNT_SID
        assert kwargs["endpoint"] == "messages"
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
