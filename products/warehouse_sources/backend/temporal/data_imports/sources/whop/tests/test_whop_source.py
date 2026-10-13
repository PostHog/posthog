import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.whop import WhopSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.whop.settings import SCHEMA_TO_WEBHOOK_EVENTS
from products.warehouse_sources.backend.temporal.data_imports.sources.whop.source import WhopSource

API_CLIENT_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.whop.source.api_client"

WEBHOOK_URL = "https://ph.example/webhook"


class TestWhopSource:
    def setup_method(self):
        self.source = WhopSource()
        self.team_id = 123
        self.config = WhopSourceConfig(api_key="test-api-key", company_id="biz_test")

    @pytest.mark.parametrize(
        "observed_error,non_retryable",
        [
            (
                "400 Client Error: Bad Request for url: https://api.whop.com/api/v1/payments"
                "?first=100&company_id=biz_example | api error: code=bad_request",
                True,
            ),
            ("429 Client Error: Too Many Requests for url: https://api.whop.com/api/v1/payments", False),
            ("503 Server Error: Service Unavailable for url: https://api.whop.com/api/v1/payments", False),
        ],
    )
    def test_a_rejected_request_stops_the_sync_and_an_overload_does_not(self, observed_error, non_retryable):
        assert error_message_matches(observed_error, self.source.get_non_retryable_errors()) is non_retryable

    @pytest.mark.parametrize("schema_name, events", list(SCHEMA_TO_WEBHOOK_EVENTS.items()))
    def test_every_event_starts_with_its_schema_routing_prefix(self, schema_name, events):
        # The hog template routes on the event's prefix, so an event whose prefix doesn't match its
        # schema's mapping key would be dropped as unroutable.
        prefix = self.source.webhook_resource_map[schema_name]
        assert all(event.split(".", 1)[0] == prefix for event in events)

    def test_webhook_template_exposes_the_signing_secret_input(self):
        template = self.source.webhook_template
        assert template is not None
        assert {field["key"] for field in template.inputs_schema} >= {
            "signing_secret",
            "schema_mapping",
            "source_id",
        }

    @pytest.mark.parametrize(
        "company_id, probe_result, schema_name, expected_valid, expected_message",
        [
            ("biz_test", (True, 200), None, True, None),
            # A 403 means a genuine key without company:basic:read; users may only grant the scopes
            # for the tables they sync, so source creation must not be blocked on it.
            ("biz_test", (False, 403), None, True, None),
            ("biz_test", (False, 403), "payments", False, "permission to read this resource"),
            ("biz_test", (False, 401), None, False, "rejected your API key"),
            ("biz_test", (False, 404), None, False, "could not find that company"),
            # An unreachable or overloaded Whop is not a bad key — saying it is sends the customer
            # off to rotate a key that works.
            ("biz_test", (False, None), None, False, "Couldn't reach Whop"),
            ("biz_test", (False, 429), None, False, "Couldn't reach Whop"),
            ("biz_test", (False, 503), None, False, "Couldn't reach Whop"),
            ("company-1", (True, 200), None, False, "start with"),
        ],
    )
    def test_validate_credentials(self, company_id, probe_result, schema_name, expected_valid, expected_message):
        config = WhopSourceConfig(api_key="test-api-key", company_id=company_id)

        with mock.patch(API_CLIENT_PATCH) as api_client:
            api_client.validate_credentials.return_value = probe_result
            is_valid, message = self.source.validate_credentials(config, self.team_id, schema_name=schema_name)

        assert is_valid is expected_valid
        if expected_message is None:
            assert message is None
        else:
            assert expected_message in (message or "")

    @pytest.mark.parametrize(
        "method_name, client_method",
        [
            ("create_webhook", "create_webhook"),
            ("delete_webhook", "delete_webhook"),
            ("get_external_webhook_info", "get_external_webhook_info"),
        ],
    )
    def test_webhook_management_passes_the_connected_company(self, method_name, client_method):
        # The webhook endpoints require company_id; dropping it would 400 every registration.
        with mock.patch(API_CLIENT_PATCH) as api_client:
            getattr(self.source, method_name)(self.config, WEBHOOK_URL, self.team_id)

        assert getattr(api_client, client_method).call_args.args == ("test-api-key", "biz_test", WEBHOOK_URL)

    def test_sync_webhook_events_forwards_the_events_for_the_selected_schemas(self):
        with mock.patch(API_CLIENT_PATCH) as api_client:
            self.source.sync_webhook_events(self.config, WEBHOOK_URL, self.team_id, ["refunds"])

        assert api_client.sync_webhook_events.call_args.args == (
            "test-api-key",
            "biz_test",
            WEBHOOK_URL,
            sorted(SCHEMA_TO_WEBHOOK_EVENTS["refunds"]),
        )

    def test_source_for_pipeline_plumbs_the_sync_inputs(self):
        inputs = mock.MagicMock()
        inputs.schema_name = "payments"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-05-01T00:00:00Z"
        manager = mock.MagicMock()

        with mock.patch(API_CLIENT_PATCH) as api_client:
            self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = api_client.whop_source.call_args.kwargs
        assert kwargs["api_key"] == "test-api-key"
        assert kwargs["company_id"] == "biz_test"
        assert kwargs["endpoint"] == "payments"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-05-01T00:00:00Z"

    def test_source_for_pipeline_withholds_the_watermark_on_a_full_refresh(self):
        # Passing a stale watermark through on a full refresh would filter out every row that
        # predates it, quietly shrinking the table the user asked to rebuild.
        inputs = mock.MagicMock()
        inputs.schema_name = "payments"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-05-01T00:00:00Z"

        with mock.patch(API_CLIENT_PATCH) as api_client:
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert api_client.whop_source.call_args.kwargs["db_incremental_field_last_value"] is None
