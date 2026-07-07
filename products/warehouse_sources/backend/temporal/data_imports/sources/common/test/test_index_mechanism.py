import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.source import BigQuerySource
from products.warehouse_sources.backend.temporal.data_imports.sources.clickhouse.source import ClickHouseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import PostgresSource
from products.warehouse_sources.backend.temporal.data_imports.sources.redshift.source import RedshiftSource
from products.warehouse_sources.backend.temporal.data_imports.sources.snowflake.source import SnowflakeSource
from products.warehouse_sources.backend.types import IndexMechanism


# These engines have no secondary indexes, so losing an override would make the sync-form
# warning suggest an action ("add an index") that's impossible to follow there.
@pytest.mark.parametrize(
    "source_class,mechanism",
    [
        (RedshiftSource, IndexMechanism.SORT_KEY),
        (BigQuerySource, IndexMechanism.PARTITION_OR_CLUSTERING),
        (SnowflakeSource, IndexMechanism.CLUSTERING_KEY),
        (ClickHouseSource, IndexMechanism.SORTING_KEY),
        (PostgresSource, IndexMechanism.INDEX),
    ],
)
def test_index_mechanism_names_the_engines_native_structure(source_class, mechanism):
    assert source_class.index_mechanism is mechanism
