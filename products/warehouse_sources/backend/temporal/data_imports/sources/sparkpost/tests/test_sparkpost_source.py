from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sparkpost import (
    SparkPostSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.settings import (
    WEBHOOK_EVENT_TYPES,
    WEBHOOK_SCHEMA_NAMES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.source import SparkPostSource

INCREMENTAL_ENDPOINTS = {"events"}


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "events",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 123,
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
    return SourceInputs(**defaults)


API_CLIENT = "products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.source.api_client"
WEBHOOK_URL = "https://app.posthog.com/public/webhooks/abc"


class TestSparkPostSourceWebhooks:
    def setup_method(self) -> None:
        self.source = SparkPostSource()
        self.team_id = 123
        self.config = SparkPostSourceConfig(api_key="sp-key", region="us")

    def test_only_the_events_table_supports_webhooks(self) -> None:
        # The management lists have no SparkPost webhook events at all. Enabling webhooks on one
        # would swap its poll out for a feed that never delivers, emptying the table.
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        assert {name for name, schema in schemas.items() if schema.supports_webhooks} == WEBHOOK_SCHEMA_NAMES

    def test_webhook_resource_map_matches_the_grouping_the_template_routes_on(self) -> None:
        assert self.source.webhook_resource_map == {"events": "message_event"}
        assert self.source.webhook_mapping_key("events") == "message_event"

    def test_webhook_template_is_a_warehouse_source_webhook(self) -> None:
        template = self.source.webhook_template

        assert template is not None
        assert template.type == "warehouse_source_webhook"
        assert {field["key"] for field in template.inputs_schema} >= {
            "authorization_header",
            "schema_mapping",
            "source_id",
        }

    def test_get_webhook_source_manager_is_bound_to_the_schema(self) -> None:
        inputs = _make_inputs()

        manager = self.source.get_webhook_source_manager(inputs)

        assert isinstance(manager, WebhookSourceManager)
        assert manager._inputs is inputs

    @pytest.mark.parametrize(
        ("eligible", "expects_events"),
        [
            (["events"], True),
            (["events", "templates"], True),
            # Nothing webhook-capable selected, so there is nothing to reconcile.
            (["templates"], False),
            ([], False),
        ],
    )
    def test_desired_webhook_events(self, eligible: list[str], expects_events: bool) -> None:
        desired = self.source.get_desired_webhook_events(self.config, eligible)

        assert (desired == WEBHOOK_EVENT_TYPES) is expects_events

    @mock.patch(API_CLIENT)
    def test_webhook_calls_are_routed_to_the_selected_region(self, mock_api: mock.MagicMock) -> None:
        # Region and key travel together: SparkPost's US and EU stacks are separate accounts, so a
        # webhook registered against the wrong host silently never fires.
        config = SparkPostSourceConfig(api_key="sp-key", region="eu")

        self.source.create_webhook(config, WEBHOOK_URL, self.team_id)
        self.source.get_external_webhook_info(config, WEBHOOK_URL, self.team_id)
        self.source.delete_webhook(config, WEBHOOK_URL, self.team_id)
        self.source.sync_webhook_events(config, WEBHOOK_URL, self.team_id, ["events"])

        mock_api.create_webhook.assert_called_once_with("eu", "sp-key", WEBHOOK_URL)
        mock_api.get_external_webhook_info.assert_called_once_with("eu", "sp-key", WEBHOOK_URL)
        mock_api.delete_webhook.assert_called_once_with("eu", "sp-key", WEBHOOK_URL)
        mock_api.sync_webhook_events.assert_called_once_with("eu", "sp-key", WEBHOOK_URL, WEBHOOK_EVENT_TYPES)
