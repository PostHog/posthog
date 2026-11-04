"""The ClickHouse tables core creates and migrates for this product.

Wiring, not data: `posthog/clickhouse/schema.py` builds these in a local or test ClickHouse, and
the migration that created them applies the same definitions to a cluster.
"""

from products.workflows.backend.models.message_assets_sql import (
    DISTRIBUTED_MESSAGE_ASSETS_TABLE_SQL as DISTRIBUTED_MESSAGE_ASSETS_TABLE_SQL,
    KAFKA_MESSAGE_ASSETS_TABLE_SQL as KAFKA_MESSAGE_ASSETS_TABLE_SQL,
    MESSAGE_ASSETS_DATA_TABLE_SQL as MESSAGE_ASSETS_DATA_TABLE_SQL,
    MESSAGE_ASSETS_MV_SQL as MESSAGE_ASSETS_MV_SQL,
)
