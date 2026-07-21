from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PaddleSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.constants import RESOURCE_TO_PADDLE_ENTITY
from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.settings import (
    ENDPOINTS,
    PADDLE_WEBHOOK_EVENTS,
    RESOURCE_TO_PADDLE_EVENTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.source import PaddleSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.paddle.source"

WEBHOOK_URL = "https://webhooks.us.posthog.com/public/webhooks/dwh/some-hog-fn-id"


def _config(environment: str = "live") -> PaddleSourceConfig:
    return PaddleSourceConfig.from_dict({"paddle_api_key": "pdl_key", "environment": environment})


class TestPaddleWebhookInvariants:
    def test_event_prefixes_match_resource_map(self):
        # The Hog template routes on the event_type prefix and looks it up in schema_mapping,
        # whose keys come from RESOURCE_TO_PADDLE_ENTITY — an event whose prefix has no map
        # entry is silently skipped, so the two must cover each other exactly.
        event_prefixes = {event.split(".")[0] for event in PADDLE_WEBHOOK_EVENTS}
        assert event_prefixes == set(RESOURCE_TO_PADDLE_ENTITY.values())

    def test_every_endpoint_has_events_and_entity(self):
        assert set(RESOURCE_TO_PADDLE_EVENTS.keys()) == set(ENDPOINTS)
        assert set(RESOURCE_TO_PADDLE_ENTITY.keys()) == set(ENDPOINTS)

    def test_events_belong_to_their_resource(self):
        for resource, events in RESOURCE_TO_PADDLE_EVENTS.items():
            prefix = RESOURCE_TO_PADDLE_ENTITY[resource]
            assert all(event.startswith(f"{prefix}.") for event in events)


class TestPaddleSourceConfigCompat:
    def test_legacy_config_without_environment_defaults_to_live(self):
        # Sources created before the environment field existed must keep working
        # against the live API.
        config = PaddleSourceConfig.from_dict({"paddle_api_key": "pdl_key"})
        assert config.environment == "live"

    def test_environment_select_defaults_to_live(self):
        fields = PaddleSource().get_source_config.fields
        environment_field = next(f for f in fields if f.name == "environment")
        assert isinstance(environment_field, SourceFieldSelectConfig)
        assert environment_field.defaultValue == "live"
        assert {option.value for option in environment_field.options} == {"live", "sandbox"}

    def test_signing_secret_is_a_secret_webhook_field(self):
        webhook_fields = PaddleSource().get_source_config.webhookFields
        assert webhook_fields is not None
        secret_field = next(f for f in webhook_fields if f.name == "signing_secret")
        assert isinstance(secret_field, SourceFieldInputConfig)
        assert secret_field.secret is True


class TestPaddleSourceSchemas:
    def test_all_schemas_support_webhooks_none_webhook_only(self):
        schemas = PaddleSource().get_schemas(config=MagicMock(), team_id=1)
        assert len(schemas) == len(ENDPOINTS)
        for schema in schemas:
            assert schema.supports_webhooks is True
            assert schema.webhook_only is False


class TestPaddleSourceWebhookDelegation:
    @parameterized.expand(
        [
            ("create", "create_paddle_webhook", "create_webhook"),
            ("delete", "delete_paddle_webhook", "delete_webhook"),
            ("info", "get_paddle_external_webhook_info", "get_external_webhook_info"),
        ]
    )
    def test_webhook_methods_thread_environment(self, _name, delegate_name, method_name):
        # A sandbox source managing its webhook against the live API would silently
        # target a destination nobody ever calls.
        with patch(f"{SOURCE_MODULE}.{delegate_name}") as mock_delegate:
            getattr(PaddleSource(), method_name)(_config("sandbox"), WEBHOOK_URL, team_id=1)
        mock_delegate.assert_called_once_with("pdl_key", "sandbox", WEBHOOK_URL)

    def test_sync_webhook_events_sends_full_event_list(self):
        with patch(f"{SOURCE_MODULE}.update_paddle_webhook_events") as mock_update:
            PaddleSource().sync_webhook_events(
                _config("sandbox"), WEBHOOK_URL, team_id=1, eligible_schema_names=["customers"]
            )
        # All known events regardless of selection — destinations self-heal as tables
        # are enabled later.
        mock_update.assert_called_once_with("pdl_key", "sandbox", WEBHOOK_URL, list(PADDLE_WEBHOOK_EVENTS))

    def test_webhook_template_identity(self):
        template = PaddleSource().webhook_template
        assert template is not None
        assert template.id == "template-warehouse-source-paddle"
        assert template.type == "warehouse_source_webhook"

    def test_resource_map_is_entity_map(self):
        assert PaddleSource().webhook_resource_map == RESOURCE_TO_PADDLE_ENTITY


class TestPaddleSourcePipelineWiring:
    def test_source_for_pipeline_threads_environment_and_webhook_manager(self):
        source = PaddleSource()
        inputs = MagicMock()
        inputs.schema_name = "transactions"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = None

        with patch(f"{SOURCE_MODULE}.paddle_source") as mock_paddle_source:
            source.source_for_pipeline(_config("sandbox"), resumable_source_manager=MagicMock(), inputs=inputs)

        kwargs = mock_paddle_source.call_args[1]
        assert kwargs["environment"] == "sandbox"
        assert isinstance(kwargs["webhook_source_manager"], WebhookSourceManager)
