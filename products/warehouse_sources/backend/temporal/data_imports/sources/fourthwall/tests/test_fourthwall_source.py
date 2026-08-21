from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.fourthwall.settings import (
    ALL_WEBHOOK_EVENTS,
    INCREMENTAL_ENDPOINTS,
    INCREMENTAL_FIELDS,
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

    def test_api_version_matches_the_path_the_code_calls(self):
        # The pin has to name the version the requests actually use, or the deprecation and
        # upgrade paths point at the wrong API.
        assert self.source.supported_versions == ("v1.0",)
        assert self.source.resolve_api_version(None) == "v1.0"

    def test_only_orders_supports_incremental(self):
        # Advertising incremental on an endpoint with no server-side timestamp filter would
        # fetch every page anyway while pretending the sync got cheaper.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        incremental = {name for name, schema in schemas.items() if schema.supports_incremental}
        assert incremental == set(INCREMENTAL_ENDPOINTS) == {"orders"}
        assert schemas["orders"].incremental_fields == INCREMENTAL_FIELDS["orders"]

    def test_webhook_capable_schemas(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        assert {name for name, schema in schemas.items() if schema.supports_webhooks} == set(WEBHOOK_SCHEMA_NAMES)
        assert all(not schema.webhook_only for schema in schemas.values())

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

    def test_get_desired_webhook_events_covers_eligible_schemas_only(self):
        events = self.source.get_desired_webhook_events(self.config, ["orders", "donations"])
        assert events == sorted(SCHEMA_TO_WEBHOOK_EVENTS["orders"] + SCHEMA_TO_WEBHOOK_EVENTS["donations"])

    def test_get_desired_webhook_events_ignores_polling_only_schemas(self):
        assert self.source.get_desired_webhook_events(self.config, ["products"]) == []

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
