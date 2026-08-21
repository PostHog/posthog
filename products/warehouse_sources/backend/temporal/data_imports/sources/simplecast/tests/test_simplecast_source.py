import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import UNVERSIONED_API_VERSION
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.simplecast import (
    SimpleCastSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.simplecast.settings import (
    SIMPLECAST_API_VERSION_2_0,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.simplecast.source import SimpleCastSource


class TestSimpleCastSource:
    def setup_method(self) -> None:
        self.source = SimpleCastSource()
        self.team_id = 123
        self.config = SimpleCastSourceConfig(api_key="sc-token")

    def test_supports_legacy_and_2_0_with_2_0_default(self) -> None:
        # 2.0 is the live Simplecast API and the new default; the legacy placeholder stays supported
        # so existing pinned rows keep resolving to their unchanged wire behaviour.
        assert self.source.supported_versions == (UNVERSIONED_API_VERSION, SIMPLECAST_API_VERSION_2_0)
        assert self.source.default_version == SIMPLECAST_API_VERSION_2_0

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.simplecast.source.simplecast_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "podcasts"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "sc-token"
        assert kwargs["endpoint"] == "podcasts"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Simplecast schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
