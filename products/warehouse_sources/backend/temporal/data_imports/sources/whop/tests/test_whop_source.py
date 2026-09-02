import pytest
from unittest import mock

from posthog.schema import ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.whop import WhopSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.whop.settings import (
    ALL_WEBHOOK_EVENTS,
    ENDPOINTS,
    INCREMENTAL_ENDPOINTS,
    MERGE_ONLY_ENDPOINTS,
    SCHEMA_TO_WEBHOOK_EVENTS,
    WEBHOOK_SCHEMA_NAMES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.whop.source import WhopSource

API_CLIENT_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.whop.source.api_client"

WEBHOOK_URL = "https://ph.example/webhook"


class TestWhopSource:
    def setup_method(self):
        self.source = WhopSource()
        self.team_id = 123
        self.config = WhopSourceConfig(api_key="test-api-key", company_id="biz_test")

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Whop"
        assert config.label == "Whop"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # The source must ship visible: unreleasedSource hides it from every user.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/whop"

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_incremental_support_matches_the_endpoint_catalog(self, endpoint):
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)

        assert schema.supports_incremental is (endpoint in INCREMENTAL_ENDPOINTS)
        if schema.supports_incremental:
            assert [f["field"] for f in schema.incremental_fields] == ["created_at"]
        else:
            assert schema.incremental_fields == []
        # Endpoints paged newest-first re-yield watermark boundary rows, which append would
        # duplicate; only a merge on `id` dedupes them.
        assert schema.supports_append is (endpoint in INCREMENTAL_ENDPOINTS and endpoint not in MERGE_ONLY_ENDPOINTS)

    def test_canonical_descriptions_only_describe_real_schemas(self):
        # A key that doesn't match a schema name is silently ignored, so the descriptions would
        # never reach the table they were written for.
        assert set(self.source.get_canonical_descriptions()) <= set(ENDPOINTS)

    def test_webhook_resource_map_routes_by_distinct_event_prefix(self):
        mapping = self.source.webhook_resource_map

        assert set(mapping) == set(WEBHOOK_SCHEMA_NAMES)
        # `dispute` and `dispute_alert` share a prefix boundary; collapsing them would file every
        # dispute alert into the disputes table.
        assert len(set(mapping.values())) == len(mapping)
        assert mapping["disputes"] == "dispute"
        assert mapping["dispute_alerts"] == "dispute_alert"

    @pytest.mark.parametrize("schema_name, events", list(SCHEMA_TO_WEBHOOK_EVENTS.items()))
    def test_every_event_starts_with_its_schema_routing_prefix(self, schema_name, events):
        # The hog template routes on the event's prefix, so an event whose prefix doesn't match its
        # schema's mapping key would be dropped as unroutable.
        prefix = self.source.webhook_resource_map[schema_name]
        assert all(event.split(".", 1)[0] == prefix for event in events)

    def test_desired_webhook_events_are_deduped_and_within_the_catalog(self):
        events = self.source.get_desired_webhook_events(self.config, ["payments", "payments", "refunds"])

        assert events == sorted(set(SCHEMA_TO_WEBHOOK_EVENTS["payments"] + SCHEMA_TO_WEBHOOK_EVENTS["refunds"]))
        assert set(events) <= set(ALL_WEBHOOK_EVENTS)

    def test_desired_webhook_events_ignores_schemas_with_no_events(self):
        assert self.source.get_desired_webhook_events(self.config, ["affiliates"]) == []

    def test_webhook_template_exposes_the_signing_secret_input(self):
        template = self.source.webhook_template
        assert template is not None
        assert {field["key"] for field in template.inputs_schema} >= {
            "signing_secret",
            "schema_mapping",
            "source_id",
        }

    @pytest.mark.parametrize(
        "company_id, probe_result, schema_name, expected_valid",
        [
            ("biz_test", (True, 200), None, True),
            # A 403 means a genuine key without company:basic:read; users may only grant the scopes
            # for the tables they sync, so source creation must not be blocked on it.
            ("biz_test", (False, 403), None, True),
            ("biz_test", (False, 403), "payments", False),
            ("biz_test", (False, 401), None, False),
            ("biz_test", (False, 404), None, False),
            ("biz_test", (False, None), None, False),
            ("company-1", (True, 200), None, False),
        ],
    )
    def test_validate_credentials(self, company_id, probe_result, schema_name, expected_valid):
        config = WhopSourceConfig(api_key="test-api-key", company_id=company_id)

        with mock.patch(API_CLIENT_PATCH) as api_client:
            api_client.validate_credentials.return_value = probe_result
            is_valid, message = self.source.validate_credentials(config, self.team_id, schema_name=schema_name)

        assert is_valid is expected_valid
        assert (message is None) is expected_valid

    def test_validate_credentials_skips_the_probe_for_a_malformed_company_id(self):
        config = WhopSourceConfig(api_key="test-api-key", company_id="acme")

        with mock.patch(API_CLIENT_PATCH) as api_client:
            self.source.validate_credentials(config, self.team_id)

        api_client.validate_credentials.assert_not_called()

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
