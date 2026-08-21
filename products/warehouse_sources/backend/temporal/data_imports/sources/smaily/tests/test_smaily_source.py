import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.smaily import SmailySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.smaily.source import SmailySource


class TestSmailySource:
    def setup_method(self) -> None:
        self.source = SmailySource()
        self.team_id = 123
        self.config = SmailySourceConfig(subdomain="acme", username="user", password="pass")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.smaily.source.smaily_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "campaigns"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["subdomain"] == "acme"
        assert kwargs["username"] == "user"
        assert kwargs["password"] == "pass"
        assert kwargs["endpoint"] == "campaigns"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Smaily schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
