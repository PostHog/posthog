import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.partnerstack import (
    PartnerStackSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerstack.source import PartnerStackSource


class TestPartnerStackSource:
    def setup_method(self) -> None:
        self.source = PartnerStackSource()
        self.team_id = 123
        self.config = PartnerStackSourceConfig(public_key="pub", private_key="priv")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.partnerstack.source.partnerstack_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "partnerships"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["public_key"] == "pub"
        assert kwargs["private_key"] == "priv"
        assert kwargs["endpoint"] == "partnerships"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown PartnerStack schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
