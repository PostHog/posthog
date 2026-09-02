from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sparkpost import (
    SparkPostSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.settings import (
    ENDPOINTS,
    LIMITED_RETENTION_ENDPOINTS,
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


class TestSparkPostSource:
    def setup_method(self) -> None:
        self.source = SparkPostSource()
        self.team_id = 123
        self.config = SparkPostSourceConfig(api_key="sp-key", region="us")

    def test_region_is_a_connection_host_field(self) -> None:
        # Changing the region must force the API key to be re-entered so it's never sent to a
        # freshly-specified host.
        assert self.source.connection_host_fields == ["region"]

    def test_get_schemas_returns_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_incremental_flags(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        for name in INCREMENTAL_ENDPOINTS:
            assert schemas[name].supports_incremental is True
            assert schemas[name].supports_append is True
            assert schemas[name].incremental_fields == [
                {
                    "label": "timestamp",
                    "type": "datetime",
                    "field": "timestamp",
                    "field_type": "datetime",
                }
            ]

        for name in set(ENDPOINTS) - INCREMENTAL_ENDPOINTS:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_retention_description(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        for name in LIMITED_RETENTION_ENDPOINTS:
            assert schemas[name].description is not None
        assert schemas["templates"].description is None

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["templates"])
        assert len(schemas) == 1
        assert schemas[0].name == "templates"

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.source.sparkpost_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(schema_name="templates", team_id=99, job_id="job-xyz")
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            region="us",
            api_key="sp-key",
            endpoint="templates",
            team_id=99,
            job_id="job-xyz",
            resumable_source_manager=manager,
            webhook_source_manager=mock.ANY,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.source.sparkpost_source")
    def test_source_for_pipeline_passes_incremental_value_when_enabled(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(
            schema_name="events",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            incremental_field="timestamp",
        )
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.source.sparkpost_source")
    def test_source_for_pipeline_omits_incremental_value_when_disabled(self, mock_source: mock.MagicMock) -> None:
        # When incremental is off the stored watermark must not leak through as a server-side filter.
        inputs = _make_inputs(
            schema_name="events",
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None


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

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.source.sparkpost_source")
    def test_source_for_pipeline_passes_a_webhook_manager(self, mock_source: mock.MagicMock) -> None:
        self.source.source_for_pipeline(self.config, mock.MagicMock(spec=ResumableSourceManager), _make_inputs())

        _, kwargs = mock_source.call_args
        assert isinstance(kwargs["webhook_source_manager"], WebhookSourceManager)
