import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.dockerhub.source import DockerhubSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dockerhub import (
    DockerhubSourceConfig,
)


class TestDockerhubSource:
    def setup_method(self) -> None:
        self.source = DockerhubSource()
        self.team_id = 123
        self.config = DockerhubSourceConfig(username="tom", personal_access_token="dckr_pat_token")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dockerhub.source.dockerhub_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "repositories"
        manager = mock.MagicMock()
        config = DockerhubSourceConfig(username="tom", personal_access_token="dckr_pat_token", namespace="my-org")

        self.source.source_for_pipeline(config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["username"] == "tom"
        assert kwargs["personal_access_token"] == "dckr_pat_token"
        assert kwargs["namespace"] == "my-org"
        assert kwargs["endpoint"] == "repositories"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Docker Hub schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
