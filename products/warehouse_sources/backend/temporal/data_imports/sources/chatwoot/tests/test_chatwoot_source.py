import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.source import ChatwootSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.chatwoot import (
    ChatwootSourceConfig,
)


class TestChatwootSource:
    def setup_method(self):
        self.source = ChatwootSource()
        self.team_id = 123
        self.config = ChatwootSourceConfig(account_id="7", api_access_token="token", host="https://chat.example.com")

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
