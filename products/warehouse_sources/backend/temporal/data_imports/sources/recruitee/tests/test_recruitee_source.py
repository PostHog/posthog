from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.recruitee import (
    RecruiteeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recruitee.source import RecruiteeSource


class TestRecruiteeSource:
    def setup_method(self) -> None:
        self.source = RecruiteeSource()
        self.team_id = 123
        self.config = RecruiteeSourceConfig(company_id="acme", api_token="rc-token")

    def test_connection_host_fields_pins_company_id(self) -> None:
        # The secret token is sent to a path derived from company_id, so retargeting the company ID
        # must re-require the token.
        assert self.source.connection_host_fields == ["company_id"]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.recruitee.source.recruitee_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "candidates"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["company_id"] == "acme"
        assert kwargs["api_token"] == "rc-token"
        assert kwargs["endpoint"] == "candidates"
        assert kwargs["resumable_source_manager"] is manager
