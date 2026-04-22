# BigQuery Marketing Source Adapter

from .self_managed import SelfManagedAdapter


class BigQueryAdapter(SelfManagedAdapter):
    """
    Adapter for BigQuery external marketing data.
    BigQuery is a "non-native" managed external source - it connects to Google BigQuery
    tables that users configure with field mappings for marketing analytics.

    Shares all field resolution and query-building logic with SelfManagedAdapter,
    differing only in the source type identifier.
    """

    def get_source_type(self) -> str:
        return "BigQuery"
