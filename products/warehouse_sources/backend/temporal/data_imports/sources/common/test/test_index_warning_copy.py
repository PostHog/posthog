import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.source import BigQuerySource
from products.warehouse_sources.backend.temporal.data_imports.sources.clickhouse.source import ClickHouseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import PostgresSource
from products.warehouse_sources.backend.temporal.data_imports.sources.redshift.source import RedshiftSource
from products.warehouse_sources.backend.temporal.data_imports.sources.snowflake.source import SnowflakeSource


# These engines have no secondary indexes, so losing an override would make the sync-form
# warning suggest an action ("add an index") that's impossible to follow there.
@pytest.mark.parametrize(
    "source_class,mechanism",
    [
        (RedshiftSource, "sort key"),
        (BigQuerySource, "partition or clustering column"),
        (SnowflakeSource, "clustering key"),
        (ClickHouseSource, "sorting key"),
        (PostgresSource, "index"),
    ],
)
def test_index_warning_copy_names_the_engines_native_mechanism(source_class, mechanism):
    copy = source_class.index_warning_copy
    assert copy["mechanism"] == mechanism
    assert copy["suggestion"]
