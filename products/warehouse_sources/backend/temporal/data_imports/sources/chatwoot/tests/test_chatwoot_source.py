import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.chatwoot import ChatwootResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.source import ChatwootSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ChatwootSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestChatwootSource:
    def setup_method(self):
        self.source = ChatwootSource()
        self.team_id = 123
        self.config = ChatwootSourceConfig(account_id="7", api_access_token="token", host="https://chat.example.com")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.CHATWOOT

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Chatwoot"
        assert config.label == "Chatwoot"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/chatwoot.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["host", "account_id", "api_access_token"]

    def test_access_token_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_access_token"
        )
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    def test_host_is_a_connection_host_field(self):
        # Retargeting the host must force re-entering the token, or the stored token could be
        # exfiltrated to an attacker-controlled server.
        assert self.source.connection_host_fields == ["host"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://chat.example.com/api/v1/accounts/7/contacts?page=1",
            "404 Client Error: Not Found for url: https://app.chatwoot.com/api/v1/accounts/999/agents",
            "Chatwoot host must use HTTPS",
            "Chatwoot account ID must be a number",
        ],
    )
    def test_non_retryable_errors_match_permanent_failures(self, observed_error):
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    def test_non_retryable_errors_do_not_match_transient_failures(self):
        transient = "500 Server Error for url: https://app.chatwoot.com/api/v1/accounts/1/contacts"
        assert not any(key in transient for key in self.source.get_non_retryable_errors())

    def test_get_schemas_are_full_refresh_with_webhook_deltas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # No Chatwoot list endpoint has a server-side timestamp filter, so nothing may advertise
        # incremental sync.
        assert not any(schema.supports_incremental or schema.supports_append for schema in schemas)
        assert {schema.name for schema in schemas if schema.supports_webhooks} == {"conversations", "messages"}

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["contacts"])
        assert [schema.name for schema in schemas] == ["contacts"]

    @pytest.mark.parametrize(
        "mock_return",
        [(True, None), (False, "Chatwoot account not found. Check the account ID and instance URL.")],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.source.validate_chatwoot_credentials"
    )
    def test_validate_credentials_plumbs_config(self, mock_validate, mock_return):
        mock_validate.return_value = mock_return

        assert self.source.validate_credentials(self.config, self.team_id) == mock_return
        mock_validate.assert_called_once_with(
            self.config.host, self.config.account_id, self.config.api_access_token, self.team_id
        )

    def test_get_resumable_source_manager_binds_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ChatwootResumeConfig

    def test_webhook_resource_map_covers_webhook_schemas(self):
        assert self.source.webhook_resource_map == {"conversations": "conversation", "messages": "message"}

    def test_webhook_template_routes_by_event_prefix(self):
        template = self.source.webhook_template

        assert template is not None
        assert template.type == "warehouse_source_webhook"
        assert template.id == "template-warehouse-source-chatwoot"
        input_keys = {schema_input["key"] for schema_input in template.inputs_schema or []}
        assert {"signing_secret", "bypass_signature_check", "schema_mapping", "source_id"} <= input_keys

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.source.create_chatwoot_webhook"
    )
    def test_create_webhook_plumbs_config(self, mock_create):
        self.source.create_webhook(self.config, "https://ph/webhook", self.team_id)

        args = mock_create.call_args.args
        assert args[:5] == (
            self.config.host,
            self.config.account_id,
            self.config.api_access_token,
            "https://ph/webhook",
            self.team_id,
        )

    def test_desired_webhook_events_cover_all_mapped_events(self):
        events = self.source.get_desired_webhook_events(self.config, ["conversations"])

        assert events is not None
        assert set(events) == {
            "conversation_created",
            "conversation_updated",
            "conversation_status_changed",
            "message_created",
            "message_updated",
        }

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.source.chatwoot_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_chatwoot_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "conversations"
        inputs.team_id = self.team_id
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_chatwoot_source.call_args.kwargs
        assert kwargs["host"] == self.config.host
        assert kwargs["account_id"] == "7"
        assert kwargs["api_access_token"] == "token"
        assert kwargs["endpoint"] == "conversations"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["webhook_source_manager"] is not None

    def test_source_for_pipeline_rejects_unknown_schema(self):
        inputs = mock.MagicMock()
        inputs.schema_name = "not-a-schema"

        with pytest.raises(ValueError, match="Unknown Chatwoot schema"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
