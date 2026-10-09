import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.calendly.calendly import (
    CALENDLY_API_VERSION_V1,
    CALENDLY_API_VERSION_V2,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.calendly.settings import CALENDLY_WEBHOOK_EVENTS
from products.warehouse_sources.backend.temporal.data_imports.sources.calendly.source import CalendlySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.calendly import (
    CalendlySourceConfig,
)


def _make_inputs(schema_name: str = "scheduled_events", **overrides):
    defaults = {
        "schema_name": schema_name,
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return mock.MagicMock(**defaults)


class TestCalendlySource:
    def setup_method(self):
        self.source = CalendlySource()
        self.team_id = 123
        self.config = CalendlySourceConfig(personal_access_token="cal_test_token")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message_fragment",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Create a new token"),
            ((False, 403), False, "required permissions"),
            ((False, None), False, "couldn't reach Calendly"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.calendly.source.validate_calendly_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message_fragment):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if expected_message_fragment is None:
            assert error_message is None
        else:
            assert error_message is not None
            assert expected_message_fragment in error_message
        mock_validate.assert_called_once_with(self.config.personal_access_token)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.calendly.source.calendly_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_calendly_source):
        inputs = _make_inputs(
            schema_name="scheduled_events",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00.000000Z",
        )
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_calendly_source.assert_called_once()
        kwargs = mock_calendly_source.call_args.kwargs
        assert kwargs["token"] == "cal_test_token"
        assert kwargs["endpoint"] == "scheduled_events"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00.000000Z"

    def test_supported_versions_declares_both_and_defaults_to_v2(self):
        # New sources must start on v2; v1 stays supported so existing pins keep resolving.
        assert self.source.default_version == CALENDLY_API_VERSION_V2
        assert set(self.source.supported_versions) == {CALENDLY_API_VERSION_V1, CALENDLY_API_VERSION_V2}

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.calendly.source.calendly_source")
    def test_source_for_pipeline_drops_last_value_when_not_incremental(self, mock_calendly_source):
        inputs = _make_inputs(
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00.000000Z",
        )

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_calendly_source.call_args.kwargs["db_incremental_field_last_value"] is None


WEBHOOK_URL = "https://webhooks.us.posthog.com/public/webhooks/dwh/hog-fn-1"
WEBHOOK_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.calendly.source"


class TestCalendlySourceWebhooks:
    def setup_method(self):
        self.source = CalendlySource()
        self.team_id = 123
        self.config = CalendlySourceConfig(personal_access_token="cal_test_token")

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
