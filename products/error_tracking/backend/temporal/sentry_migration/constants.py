WORKFLOW_NAME = "sentry-migration"
WORKFLOW_ID_PREFIX = "sentry-migration"

# Observability tag required by capture_batch_internal.
EVENT_SOURCE = "sentry_migration"

# Warehouse schemas that must have completed their initial sync before the import can run.
REQUIRED_SCHEMA_NAMES = ("issues", "issue_events")

IMPORT_PAGE_SIZE = 500
STATUS_SYNC_PAGE_SIZE = 1000
STATUS_SYNC_CHUNK_SIZE = 500
