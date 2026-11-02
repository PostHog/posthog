from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.onepagecrm import (
    OnepagecrmSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onepagecrm.source import OnepagecrmSource


class TestOnepagecrmSource:
    def setup_method(self) -> None:
        self.source = OnepagecrmSource()
        self.team_id = 123
        self.config = OnepagecrmSourceConfig(user_id="uid-1", api_key="key-1")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.onepagecrm.source.onepagecrm_source")
    def test_source_for_pipeline_plumbs_incremental_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "contacts"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["user_id"] == "uid-1"
        assert kwargs["api_key"] == "key-1"
        assert kwargs["endpoint"] == "contacts"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000

    def test_source_for_pipeline_drops_watermark_on_full_refresh(self) -> None:
        result = SourceDriver(self.source, self.config).run(
            "contacts",
            [ScriptedResponse(json={"data": {"contacts": []}})],
            should_use_incremental_field=False,
            db_incremental_field_last_value=1700000000,
        )

        assert result.raised is None
        assert result.params("sort_by") == ["created_at"]
        assert result.params("modified_since") == [None]
