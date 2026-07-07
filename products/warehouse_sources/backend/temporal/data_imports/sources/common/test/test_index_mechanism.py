import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.source import BigQuerySource
from products.warehouse_sources.backend.temporal.data_imports.sources.clickhouse.source import ClickHouseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import _BaseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.base import SQLSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.implementation import (
    SQLSourceImplementation,
)
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


def test_sql_sources_that_detect_indexed_columns_declare_a_mechanism():
    # A source that detects indexed columns can emit `is_indexed=False`, which shows the
    # "No {mechanism} detected" warning — silently inheriting the default mechanism there
    # is how a new warehouse source ends up telling users to add an index it can't have.
    offenders = []
    for source in SourceRegistry.get_all_sources().values():
        if not isinstance(source, SQLSource):
            continue
        detects_indexed_columns = (
            type(source.get_implementation).get_leading_index_columns
            is not SQLSourceImplementation.get_leading_index_columns
            or type(source).get_schemas is not SQLSource.get_schemas
        )
        declares_mechanism = any(
            "index_mechanism" in vars(klass) for klass in type(source).__mro__ if klass is not _BaseSource
        )
        if detects_indexed_columns and not declares_mechanism:
            offenders.append(type(source).__name__)

    assert not offenders, (
        f"{offenders} detect indexed columns but inherit the default index_mechanism. "
        "Declare `index_mechanism = IndexMechanism.<X>` on the source class so the sync-form "
        "warning names the engine's actual fast-lookup structure (sort key, clustering key, ...)."
    )
