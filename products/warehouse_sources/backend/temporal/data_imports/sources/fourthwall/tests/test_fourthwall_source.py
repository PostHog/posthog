import pytest
from unittest import mock

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.fourthwall.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fourthwall.settings import (
    ALL_WEBHOOK_EVENTS,
    ENDPOINTS,
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

    @pytest.mark.parametrize(
        "field_name, expected_type, expected_secret",
        [
            ("username", SourceFieldInputConfigType.TEXT, False),
            ("password", SourceFieldInputConfigType.PASSWORD, True),
        ],
    )
    def test_credential_fields(self, field_name, expected_type, expected_secret):
        # The API user's password is a full-access shop credential; storing it unmasked would
        # expose it in the source list.
        field = next(
            f
            for f in self.source.get_source_config.fields
            if isinstance(f, SourceFieldInputConfig) and f.name == field_name
        )
        assert field.type == expected_type
        assert field.secret is expected_secret
        assert field.required is True

    def test_api_version_matches_the_path_the_code_calls(self):
        # The pin has to name the version the requests actually use, or the deprecation and
        # upgrade paths point at the wrong API.
        assert self.source.supported_versions == ("v1.0",)
        assert self.source.resolve_api_version(None) == "v1.0"

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.fourthwall.com/open-api/v1.0/order?page=0",
            "403 Client Error: Forbidden for url: https://api.fourthwall.com/open-api/v1.0/donations",
        ],
    )
    def test_auth_failures_are_non_retryable(self, observed_error):
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.fourthwall.com/open-api/v1.0/order",
            "500 Server Error for url: https://api.fourthwall.com/open-api/v1.0/order",
        ],
    )
    def test_transient_failures_stay_retryable(self, other_error):
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    def test_only_orders_supports_incremental(self):
        # Advertising incremental on an endpoint with no server-side timestamp filter would
        # fetch every page anyway while pretending the sync got cheaper.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        incremental = {name for name, schema in schemas.items() if schema.supports_incremental}
        assert incremental == set(INCREMENTAL_ENDPOINTS) == {"orders"}
        assert schemas["orders"].incremental_fields == INCREMENTAL_FIELDS["orders"]

    def test_incremental_schemas_are_merge_only(self):
        # `updatedAt` moves whenever an order changes status, so append would add a row per
        # update instead of upserting the order.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["orders"].supports_append is False

    def test_canonical_descriptions_cover_declared_tables_only(self):
        # A key that isn't a schema name is never applied, so the table silently falls back to
        # the LLM description we paid to avoid.
        assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)
        assert self.source.get_canonical_descriptions() is CANONICAL_DESCRIPTIONS

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
