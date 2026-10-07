from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.fourthwall.settings import (
    ALL_WEBHOOK_EVENTS,
    SCHEMA_TO_WEBHOOK_EVENTS,
    SCHEMA_TO_WEBHOOK_RESOURCE,
    WEBHOOK_EVENT_TO_RESOURCE,
    WEBHOOK_SCHEMA_NAMES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fourthwall.source import FourthwallSource
from products.warehouse_sources.backend.temporal.data_imports.sources.fourthwall.webhook_template import template
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fourthwall import (
    FourthwallSourceConfig,
)

API_CLIENT_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.fourthwall.source.api_client"
WEBHOOK_URL = "https://us.posthog.com/public/webhooks/abc"


class TestFourthwallSource:
    def setup_method(self):
        self.source = FourthwallSource()
        self.team_id = 123
        self.config = FourthwallSourceConfig(username="api-user", password="api-secret")

    @mock.patch(f"{API_CLIENT_PATCH}.fourthwall_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "orders"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-05-01T00:00:00Z"
        inputs.api_version = None
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["username"] == "api-user"
        assert kwargs["password"] == "api-secret"
        assert kwargs["endpoint"] == "orders"
        assert kwargs["api_version"] == "v1.0"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["webhook_source_manager"] is not None
        assert kwargs["db_incremental_field_last_value"] == "2026-05-01T00:00:00Z"

    @mock.patch(f"{API_CLIENT_PATCH}.fourthwall_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_source):
        # Passing a watermark through on a full refresh would inject a filter the user never
        # asked for and truncate the table.
        inputs = mock.MagicMock()
        inputs.schema_name = "products"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-05-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_webhook_resource_map_covers_the_webhook_schemas(self):
        assert self.source.webhook_resource_map == SCHEMA_TO_WEBHOOK_RESOURCE
        assert set(SCHEMA_TO_WEBHOOK_RESOURCE) == set(WEBHOOK_SCHEMA_NAMES)

    def test_webhook_template_resource_keys_match_the_settings_mapping(self):
        # The hog template carries its own event -> resource dict; a schema mapped to a key the
        # template never emits would drop every delivery for that table.
        for event, resource in WEBHOOK_EVENT_TO_RESOURCE.items():
            assert f"'{event}': '{resource}'" in template.code

    def test_webhook_template_declares_the_inputs_the_source_sets(self):
        assert template.type == "warehouse_source_webhook"
        input_keys = {input_schema["key"] for input_schema in template.inputs_schema}
        assert {"signing_secret", "schema_mapping", "source_id"} <= input_keys

    def test_all_webhook_events_is_the_union_of_the_schema_events(self):
        assert set(ALL_WEBHOOK_EVENTS) == set(WEBHOOK_EVENT_TO_RESOURCE)

    @mock.patch(f"{API_CLIENT_PATCH}.create_webhook")
    def test_create_webhook_delegates(self, mock_create):
        self.source.create_webhook(self.config, WEBHOOK_URL, self.team_id)
        mock_create.assert_called_once_with("api-user", "api-secret", "v1.0", WEBHOOK_URL)

    @mock.patch(f"{API_CLIENT_PATCH}.delete_webhook")
    def test_delete_webhook_delegates(self, mock_delete):
        self.source.delete_webhook(self.config, WEBHOOK_URL, self.team_id)
        mock_delete.assert_called_once_with("api-user", "api-secret", "v1.0", WEBHOOK_URL)

    @mock.patch(f"{API_CLIENT_PATCH}.get_external_webhook_info")
    def test_get_external_webhook_info_delegates(self, mock_info):
        self.source.get_external_webhook_info(self.config, WEBHOOK_URL, self.team_id)
        mock_info.assert_called_once_with("api-user", "api-secret", "v1.0", WEBHOOK_URL)

    @mock.patch(f"{API_CLIENT_PATCH}.sync_webhook_events")
    def test_sync_webhook_events_passes_desired_events(self, mock_sync):
        self.source.sync_webhook_events(self.config, WEBHOOK_URL, self.team_id, ["donations"])
        mock_sync.assert_called_once_with(
            "api-user", "api-secret", "v1.0", WEBHOOK_URL, sorted(SCHEMA_TO_WEBHOOK_EVENTS["donations"])
        )
