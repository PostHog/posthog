from unittest import mock

import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.packagist import (
    PackagistSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.packagist.source import PackagistSource


def _make_inputs(
    schema_name: str = "packages",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: str | None = None,
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=123,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        db_incremental_field_earliest_value=None,
        incremental_field="date" if should_use_incremental_field else None,
        incremental_field_type=None,
        job_id="job-id",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class TestPackagistSource:
    def setup_method(self):
        self.source = PackagistSource()
        self.team_id = 123
        self.config = PackagistSourceConfig(packages="monolog/monolog\nsymfony/console")

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["downloads"])

        assert [schema.name for schema in schemas] == ["downloads"]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.packagist.source.packagist_source")
    def test_source_for_pipeline_drops_watermark_when_not_incremental(self, mock_packagist_source):
        # A stale watermark from a previous incremental run must not leak into a full refresh.
        inputs = _make_inputs(schema_name="downloads", db_incremental_field_last_value="2026-07-01")

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_packagist_source.call_args.kwargs["db_incremental_field_last_value"] is None
