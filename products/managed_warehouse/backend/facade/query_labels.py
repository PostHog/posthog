"""Stable query-status labels shared by managed warehouse producers and readers."""

# Stable wire identifier shared by query-status producers and readers. Renaming requires
# a dual-read rollout and a drain of in-flight query statuses.
MANAGED_WAREHOUSE_QUERY_STATUS_LABEL_PREFIX = "managed-warehouse-sql-editor:"
