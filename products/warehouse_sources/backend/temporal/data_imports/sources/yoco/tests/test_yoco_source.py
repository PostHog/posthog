from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.yoco import YocoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.yoco.source import YocoSource


class TestYocoSource:
    def setup_method(self) -> None:
        self.source = YocoSource()
        self.team_id = 123
        self.config = YocoSourceConfig(api_key="yoco-key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.yoco.source.api_client")
    def test_get_endpoint_permissions_plumbs_endpoints(self, mock_client: mock.MagicMock) -> None:
        mock_client.get_endpoint_permissions.return_value = {"payments": None}
        assert self.source.get_endpoint_permissions(self.config, self.team_id, ["payments"]) == {"payments": None}
        assert mock_client.get_endpoint_permissions.call_args.args == ("yoco-key", ["payments"])

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.yoco.source.api_client")
    def test_source_for_pipeline_plumbs_arguments(self, mock_client: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "payments"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "created_at"
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_client.yoco_source.call_args.kwargs
        assert kwargs["api_key"] == "yoco-key"
        assert kwargs["endpoint"] == "payments"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        # The user's chosen cursor must reach the request layer, not the endpoint default.
        assert kwargs["incremental_field"] == "created_at"
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
