import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sagehr import SageHRSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sage_hr.source import SageHRSource


class TestSageHRSource:
    def setup_method(self) -> None:
        self.source = SageHRSource()
        self.team_id = 123
        self.config = SageHRSourceConfig(subdomain="acme", api_key="sage-key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.sage_hr.source.sage_hr_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "employees"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["subdomain"] == "acme"
        assert kwargs["api_key"] == "sage-key"
        assert kwargs["endpoint"] == "employees"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Sage HR schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
