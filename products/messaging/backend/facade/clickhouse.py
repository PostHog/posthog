"""The ClickHouse tables core creates and migrates for this product.

Wiring, not data: `posthog/clickhouse/schema.py` builds these in a local or test ClickHouse, and
the migration that created them applies the same definitions to a cluster.
"""

from products.messaging.backend.models.email_status_sql import (
    DISTRIBUTED_EMAIL_STATUS_TABLE_SQL as DISTRIBUTED_EMAIL_STATUS_TABLE_SQL,
    EMAIL_STATUS_DATA_TABLE_SQL as EMAIL_STATUS_DATA_TABLE_SQL,
    EMAIL_STATUS_MV_SQL as EMAIL_STATUS_MV_SQL,
    KAFKA_EMAIL_STATUS_TABLE_SQL as KAFKA_EMAIL_STATUS_TABLE_SQL,
)
