from unittest import mock

import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.myhours import (
    MyHoursSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.my_hours.source import MyHoursSource


def _make_inputs(schema_name: str = "clients") -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=123,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-id",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class TestMyHoursSource:
    def setup_method(self) -> None:
        self.source = MyHoursSource()
        self.team_id = 123
        self.config = MyHoursSourceConfig(api_key="mh-key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.my_hours.source.my_hours_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(schema_name="clients")

        self.source.source_for_pipeline(self.config, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "mh-key"
        assert kwargs["endpoint"] == "clients"
