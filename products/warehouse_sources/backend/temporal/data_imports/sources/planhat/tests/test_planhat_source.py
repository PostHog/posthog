from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.planhat import (
    PlanhatSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.planhat.source import PlanhatSource


class TestPlanhatSource:
    def setup_method(self) -> None:
        self.source = PlanhatSource()
        self.team_id = 123
        self.config = PlanhatSourceConfig(api_key="ph-token")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.planhat.source.validate_credentials")
    def test_validate_credentials_delegates_to_planhat(self, mock_validate: mock.MagicMock) -> None:
        # source.py owns no mapping logic — it forwards the account-wide token and returns the result verbatim.
        mock_validate.return_value = (False, "Invalid Planhat API token")
        result = self.source.validate_credentials(self.config, self.team_id)
        mock_validate.assert_called_once_with("ph-token")
        assert result == (False, "Invalid Planhat API token")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.planhat.source.planhat_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "companies"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_token"] == "ph-token"
        assert kwargs["endpoint"] == "companies"
        assert kwargs["resumable_source_manager"] is manager
