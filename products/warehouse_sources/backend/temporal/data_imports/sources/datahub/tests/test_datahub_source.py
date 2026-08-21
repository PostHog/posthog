import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.datahub.source import DatahubSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.datahub import (
    DatahubSourceConfig,
)


class TestDatahubSource:
    def setup_method(self) -> None:
        self.source = DatahubSource()
        self.team_id = 123
        self.config = DatahubSourceConfig(instance_url="https://datahub.example.com", api_token="secret-token")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.datahub.source.check_endpoint_permissions"
    )
    def test_get_endpoint_permissions_delegates_to_shared_helper(self, mock_check: mock.MagicMock) -> None:
        mock_check.return_value = {"users": "needs view privilege", "datasets": None}
        result = self.source.get_endpoint_permissions(self.config, self.team_id, ["users", "datasets"])
        assert result == {"users": "needs view privilege", "datasets": None}
        mock_check.assert_called_once_with(
            "https://datahub.example.com", "secret-token", ["users", "datasets"], self.team_id
        )

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.datahub.source.datahub_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "datasets"
        inputs.team_id = self.team_id
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["instance_url"] == "https://datahub.example.com"
        assert kwargs["api_token"] == "secret-token"
        assert kwargs["endpoint"] == "datasets"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "nope"
        with pytest.raises(ValueError, match="Unknown DataHub schema"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
