import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.unleash import (
    UnleashSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.unleash.source import UnleashSource


class TestUnleashSource:
    def setup_method(self) -> None:
        self.source = UnleashSource()
        self.team_id = 123
        self.config = UnleashSourceConfig(instance_url="https://unleash.example.com", api_token="user:secret-token")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.unleash.source.check_endpoint_permissions"
    )
    def test_get_endpoint_permissions_delegates_to_shared_helper(self, mock_check: mock.MagicMock) -> None:
        mock_check.return_value = {"users": "needs admin", "features": None}
        result = self.source.get_endpoint_permissions(self.config, self.team_id, ["users", "features"])
        assert result == {"users": "needs admin", "features": None}
        mock_check.assert_called_once_with(
            "https://unleash.example.com", "user:secret-token", ["users", "features"], self.team_id
        )

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.unleash.source.unleash_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "features"
        inputs.team_id = self.team_id
        inputs.job_id = "job-123"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["instance_url"] == "https://unleash.example.com"
        assert kwargs["api_token"] == "user:secret-token"
        assert kwargs["endpoint"] == "features"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["job_id"] == "job-123"
        assert kwargs["resumable_source_manager"] is manager
        assert "logger" not in kwargs

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "nope"
        with pytest.raises(ValueError, match="Unknown Unleash schema"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
