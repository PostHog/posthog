from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sparkpost import (
    SparkPostSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.settings import WEBHOOK_EVENT_TYPES
from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.source import SparkPostSource


class TestSparkPostSource:
    def setup_method(self) -> None:
        self.source = SparkPostSource()
        self.team_id = 123
        self.config = SparkPostSourceConfig(api_key="sp-key", region="us")

    def test_region_is_a_connection_host_field(self) -> None:
        # Changing the region must force the API key to be re-entered so it's never sent to a
        # freshly-specified host.
        assert self.source.connection_host_fields == ["region"]

    def test_source_for_pipeline_passes_incremental_value_when_enabled(self) -> None:
        result = self._run(
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            incremental_field="timestamp",
        )

        assert result.requests[0].param("from") == "2026-01-01T00:00"

    def test_source_for_pipeline_omits_incremental_value_when_disabled(self) -> None:
        # When incremental is off the stored watermark must not leak through as a server-side filter.
        result = self._run(
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )

        assert result.requests[0].param("from") != "2026-01-01T00:00"

    def _run(self, **inputs: Any) -> DriveResult:
        return SourceDriver(self.source, self.config).run(
            "events", [ScriptedResponse(json={"results": [], "links": []})], **inputs
        )


API_CLIENT = "products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.source.api_client"
WEBHOOK_URL = "https://app.posthog.com/public/webhooks/abc"


class TestSparkPostSourceWebhooks:
    def setup_method(self) -> None:
        self.source = SparkPostSource()
        self.team_id = 123
        self.config = SparkPostSourceConfig(api_key="sp-key", region="us")

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
