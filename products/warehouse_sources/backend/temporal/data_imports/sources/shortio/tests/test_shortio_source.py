import pytest
from unittest import mock

import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.shortio import (
    ShortioSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shortio.source import ShortioSource


def _make_inputs(schema_name: str = "domains") -> SourceInputs:
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


class TestShortioSource:
    def setup_method(self) -> None:
        self.source = ShortioSource()
        self.team_id = 123
        self.config = ShortioSourceConfig(api_key="sk-key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.shortio.source.shortio_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(schema_name="domains")

        self.source.source_for_pipeline(self.config, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "sk-key"
        assert kwargs["endpoint"] == "domains"

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = _make_inputs(schema_name="not_a_table")
        with pytest.raises(ValueError, match="Unknown Short.io schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, inputs)
