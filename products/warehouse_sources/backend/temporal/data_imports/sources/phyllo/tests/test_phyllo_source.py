import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.phyllo import PhylloSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.phyllo.source import PhylloSource


class TestPhylloSource:
    def setup_method(self) -> None:
        self.source = PhylloSource()
        self.team_id = 123
        self.config = PhylloSourceConfig(client_id="cid", client_secret="cs-secret", environment="production")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.phyllo.source.phyllo_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "social_contents"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["client_id"] == "cid"
        assert kwargs["client_secret"] == "cs-secret"
        assert kwargs["environment"] == "production"
        assert kwargs["endpoint"] == "social_contents"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Phyllo schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
