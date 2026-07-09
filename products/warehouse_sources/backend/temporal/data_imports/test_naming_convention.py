from posthog.ducklake.common import duckgres_data_imports_table_name

from products.warehouse_sources.backend.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor import (
    _duckgres_table_name,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _schema(source_type: str, name: str, prefix: str | None = None) -> ExternalDataSchema:
    return ExternalDataSchema(name=name, source=ExternalDataSource(source_type=source_type, prefix=prefix))


def test_reader_table_name_matches_sink_for_every_source_type():
    # The sink and existing copy/read paths must agree byte-for-byte, or cutover
    # switches readers to a table that no writer has created yet.
    for source_type in ExternalDataSourceType.values:
        for name, prefix in [("orders", None), ("Orders-2024", "acct_1"), ("a" * 90, None)]:
            schema = _schema(source_type, name, prefix)
            assert duckgres_data_imports_table_name(schema) == _duckgres_table_name(schema), (
                source_type,
                name,
                prefix,
            )
