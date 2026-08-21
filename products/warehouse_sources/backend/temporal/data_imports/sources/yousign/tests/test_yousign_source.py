import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.yousign import (
    YouSignSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.yousign.settings import WEBHOOK_EVENTS
from products.warehouse_sources.backend.temporal.data_imports.sources.yousign.source import YouSignSource


class TestYousignSource:
    def setup_method(self) -> None:
        self.source = YouSignSource()
        self.team_id = 123
        self.config = YouSignSourceConfig(api_key="key", environment="production")

    def test_webhook_resource_map_matches_event_name_prefixes(self) -> None:
        # The hog template routes on the event name prefix (`signature_request.done` ->
        # `signature_request`), so the map values must be that prefix.
        assert self.source.webhook_resource_map == {"signature_requests": "signature_request"}
        assert all(event.split(".")[0] == "signature_request" for event in WEBHOOK_EVENTS)

    def test_webhook_template_shape(self) -> None:
        template = self.source.webhook_template
        assert template is not None
        assert template.type == "warehouse_source_webhook"
        assert template.id == "template-warehouse-source-yousign"
        input_keys = {schema_input["key"] for schema_input in template.inputs_schema or []}
        assert {"signing_secret", "schema_mapping", "source_id"} <= input_keys

    def test_desired_webhook_events_cover_all_mapped_events(self) -> None:
        assert self.source.get_desired_webhook_events(self.config, ["signature_requests"]) == WEBHOOK_EVENTS

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.yousign.source.create_yousign_webhook"
    )
    def test_create_webhook_plumbs_config(self, mock_create: mock.MagicMock) -> None:
        self.source.create_webhook(self.config, "https://ph/webhook", self.team_id)
        args = mock_create.call_args.args
        assert args[:3] == ("key", "production", "https://ph/webhook")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.yousign.source.yousign_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_yousign_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "signature_requests"
        inputs.team_id = self.team_id
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "completed_at"
        inputs.db_incremental_field_last_value = "2025-03-02"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_yousign_source.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["environment"] == "production"
        assert kwargs["endpoint"] == "signature_requests"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["webhook_source_manager"] is not None
        assert kwargs["incremental_field"] == "completed_at"
        assert kwargs["db_incremental_field_last_value"] == "2025-03-02"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.yousign.source.yousign_source")
    def test_source_for_pipeline_drops_watermark_for_full_refresh(self, mock_yousign_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "signature_requests"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2025-03-02"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_yousign_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not-a-schema"
        with pytest.raises(ValueError, match="Unknown Yousign schema"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
