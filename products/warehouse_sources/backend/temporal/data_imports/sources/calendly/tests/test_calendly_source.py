import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.calendly.calendly import (
    CALENDLY_API_VERSION_V1,
    CALENDLY_API_VERSION_V2,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.calendly.settings import (
    CALENDLY_WEBHOOK_EVENTS,
    WEBHOOK_SCHEMA_NAMES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.calendly.source import CalendlySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.calendly import (
    CalendlySourceConfig,
)


class TestCalendlySource:
    def setup_method(self):
        self.source = CalendlySource()
        self.team_id = 123
        self.config = CalendlySourceConfig(personal_access_token="cal_test_token")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Calendly personal access token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.calendly.source.validate_calendly_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.personal_access_token)

    def test_supported_versions_declares_both_and_defaults_to_v2(self):
        # New sources must start on v2; v1 stays supported so existing pins keep resolving.
        assert self.source.default_version == CALENDLY_API_VERSION_V2
        assert set(self.source.supported_versions) == {CALENDLY_API_VERSION_V1, CALENDLY_API_VERSION_V2}

    def test_v1_is_deprecated_without_sunset_and_v2_is_not(self):
        # v1 is flagged so the in-product deprecation warning fires, but carries no sunset date —
        # both labels hit the same live host, so no pin is on borrowed time. The default (v2) must
        # never be deprecated.
        deprecation = self.source.get_version_deprecation(CALENDLY_API_VERSION_V1)
        assert deprecation is not None
        assert deprecation.sunset_at is None
        assert self.source.get_version_deprecation(CALENDLY_API_VERSION_V2) is None


WEBHOOK_URL = "https://webhooks.us.posthog.com/public/webhooks/dwh/hog-fn-1"
WEBHOOK_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.calendly.source"


class TestCalendlySourceWebhooks:
    def setup_method(self):
        self.source = CalendlySource()
        self.team_id = 123
        self.config = CalendlySourceConfig(personal_access_token="cal_test_token")

    def test_only_scheduled_events_accepts_webhooks(self):
        # Calendly's webhook events all describe invitee activity; only their payloads embed a
        # scheduled event, and nothing it emits matches the other four tables.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert {name for name, schema in schemas.items() if schema.supports_webhooks} == set(WEBHOOK_SCHEMA_NAMES)
        # Every table still has a working list endpoint, so none of them is webhook-only.
        assert all(not schema.webhook_only for schema in schemas.values())

    def test_routing_key_matches_the_key_the_template_looks_up(self):
        # The hog template reads a fixed key out of `schema_mapping`; if the map and the template
        # drift apart, deliveries are acked and silently dropped.
        template = self.source.webhook_template

        assert self.source.webhook_resource_map == {"scheduled_events": "scheduled_event"}
        assert self.source.webhook_mapping_key("scheduled_events") == "scheduled_event"
        assert template is not None
        assert "inputs.schema_mapping?.['scheduled_event']" in template.code

    def test_webhook_template_verifies_the_calendly_signature_header(self):
        template = self.source.webhook_template

        assert template is not None
        assert template.id == "template-warehouse-source-calendly"
        assert "calendly-webhook-signature" in template.code
        assert "produceToWarehouseWebhooks" in template.code

    def test_desired_events_do_not_narrow_with_the_selected_schemas(self):
        # Calendly subscriptions are immutable, so the event list must not depend on what the user
        # happens to have selected when the webhook is registered.
        assert self.source.get_desired_webhook_events(self.config, []) == list(CALENDLY_WEBHOOK_EVENTS)
        assert self.source.get_desired_webhook_events(self.config, ["scheduled_events"]) == list(
            CALENDLY_WEBHOOK_EVENTS
        )

    @pytest.mark.parametrize(
        "method, patched, extra_kwargs",
        [
            ("create_webhook", "create_calendly_webhook", {}),
            ("delete_webhook", "delete_calendly_webhook", {}),
            ("get_external_webhook_info", "get_calendly_webhook_info", {}),
        ],
    )
    def test_webhook_management_delegates_with_the_token(self, method, patched, extra_kwargs):
        with mock.patch(f"{WEBHOOK_MODULE}.{patched}") as delegate:
            getattr(self.source, method)(self.config, WEBHOOK_URL, self.team_id, **extra_kwargs)

        delegate.assert_called_once_with("cal_test_token", WEBHOOK_URL, CALENDLY_API_VERSION_V2)

    @pytest.mark.parametrize(
        "pin, expected",
        [
            (CALENDLY_API_VERSION_V1, CALENDLY_API_VERSION_V1),
            (None, CALENDLY_API_VERSION_V2),
        ],
    )
    def test_webhook_management_runs_against_the_pinned_version(self, pin, expected):
        with mock.patch(f"{WEBHOOK_MODULE}.create_calendly_webhook") as delegate:
            self.source.create_webhook(self.config, WEBHOOK_URL, self.team_id, api_version=pin)

        assert delegate.call_args.args[2] == expected
