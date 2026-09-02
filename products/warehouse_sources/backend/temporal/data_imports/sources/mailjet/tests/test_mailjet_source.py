from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mailjet import (
    MailjetSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.settings import (
    ENDPOINTS,
    MAILJET_WEBHOOK_EVENTS,
    SCHEMA_TO_WEBHOOK_RESOURCE,
    WEBHOOK_SCHEMA_NAMES,
    WEBHOOK_TABLE_NAME,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.source import MailJetSource
from products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.webhook_template import template

_STATISTICS_ENDPOINTS = {"openinformation", "clickstatistics"}
WEBHOOK_URL = "https://webhooks.us.posthog.com/public/webhooks/dwh/hog-fn-1"
API_CLIENT_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.source.api_client"


class TestMailJetSource:
    def setup_method(self):
        self.source = MailJetSource()
        self.team_id = 123
        self.config = MailjetSourceConfig(api_key="key", secret_key="secret")

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        for schema in schemas:
            expected_incremental = schema.name in _STATISTICS_ENDPOINTS
            assert schema.supports_incremental is expected_incremental
            assert schema.supports_append is expected_incremental
            if expected_incremental:
                assert len(schema.incremental_fields) == 1
            else:
                assert schema.incremental_fields == []

    def test_webhook_capable_schemas(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert {name for name, schema in schemas.items() if schema.supports_webhooks} == set(WEBHOOK_SCHEMA_NAMES)
        # The message event stream has no list endpoint behind it, so polling can never rebuild it
        # and the UI must offer webhook sync only.
        assert schemas[WEBHOOK_TABLE_NAME].webhook_only is True
        assert all(not schema.webhook_only for name, schema in schemas.items() if name != WEBHOOK_TABLE_NAME)

    def test_polled_schemas_never_gain_webhooks(self):
        # Mailjet's event payloads name their fields differently to /openinformation and
        # /clickstatistics (mj_contact_id vs ContactID, time vs OpenedAt, no ID at all), so routing
        # them into those tables would break the merge and disable their poll.
        schemas = self.source.get_schemas(self.config, self.team_id)
        polled_with_webhooks = {
            schema.name for schema in schemas if schema.supports_webhooks and schema.name != WEBHOOK_TABLE_NAME
        }
        assert polled_with_webhooks == set()

    def test_webhook_resource_map_covers_the_webhook_schema(self):
        assert self.source.webhook_resource_map == SCHEMA_TO_WEBHOOK_RESOURCE
        assert set(SCHEMA_TO_WEBHOOK_RESOURCE) == set(WEBHOOK_SCHEMA_NAMES)

    def test_webhook_template_routes_every_subscribed_event(self):
        assert template.type == "warehouse_source_webhook"
        # An event we register but never route would be acknowledged and silently dropped.
        for event in MAILJET_WEBHOOK_EVENTS:
            assert f"'{event}': '{WEBHOOK_TABLE_NAME}'" in template.code

    def test_get_desired_webhook_events_only_fires_for_the_webhook_schema(self):
        assert self.source.get_desired_webhook_events(self.config, [WEBHOOK_TABLE_NAME]) == list(MAILJET_WEBHOOK_EVENTS)
        assert self.source.get_desired_webhook_events(self.config, ["contact"]) == []

    def test_get_webhook_source_manager(self):
        assert isinstance(self.source.get_webhook_source_manager(mock.MagicMock()), WebhookSourceManager)

    @mock.patch(f"{API_CLIENT_PATCH}.create_webhook")
    def test_create_webhook_delegates(self, mock_create):
        self.source.create_webhook(self.config, WEBHOOK_URL, self.team_id)
        mock_create.assert_called_once_with("key", "secret", WEBHOOK_URL)

    @mock.patch(f"{API_CLIENT_PATCH}.delete_webhook")
    def test_delete_webhook_delegates(self, mock_delete):
        self.source.delete_webhook(self.config, WEBHOOK_URL, self.team_id)
        mock_delete.assert_called_once_with("key", "secret", WEBHOOK_URL)

    @mock.patch(f"{API_CLIENT_PATCH}.get_external_webhook_info")
    def test_get_external_webhook_info_delegates(self, mock_info):
        self.source.get_external_webhook_info(self.config, WEBHOOK_URL, self.team_id)
        mock_info.assert_called_once_with("key", "secret", WEBHOOK_URL)

    @mock.patch(f"{API_CLIENT_PATCH}.sync_webhook_events")
    def test_sync_webhook_events_passes_the_desired_events(self, mock_sync):
        self.source.sync_webhook_events(self.config, WEBHOOK_URL, self.team_id, [WEBHOOK_TABLE_NAME])
        mock_sync.assert_called_once_with("key", "secret", WEBHOOK_URL, list(MAILJET_WEBHOOK_EVENTS))

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["contact"])

        assert len(schemas) == 1
        assert schemas[0].name == "contact"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["nonexistent"])

        assert schemas == []

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.source.validate_mailjet_credentials"
    )
    def test_validate_credentials_success(self, mock_validate):
        mock_validate.return_value = True

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error_message is None
        mock_validate.assert_called_once_with(self.config.api_key, self.config.secret_key)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.source.validate_mailjet_credentials"
    )
    def test_validate_credentials_failure(self, mock_validate):
        mock_validate.return_value = False

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == "Invalid Mailjet API key or secret key"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.source.mailjet_source")
    def test_source_for_pipeline(self, mock_mailjet_source):
        mock_mailjet_source.return_value = mock.MagicMock()

        inputs = mock.MagicMock()
        inputs.schema_name = "contact"
        inputs.team_id = 123
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = False
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_mailjet_source.call_args.kwargs
        assert kwargs["api_key"] == self.config.api_key
        assert kwargs["secret_key"] == self.config.secret_key
        assert kwargs["endpoint"] == "contact"
        assert kwargs["team_id"] == 123
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None
        # One sync covers both paths: the poll for the REST tables, the webhook manager for the
        # pushed message events.
        assert isinstance(kwargs["webhook_source_manager"], WebhookSourceManager)
