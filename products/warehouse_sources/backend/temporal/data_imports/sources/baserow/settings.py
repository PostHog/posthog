DEFAULT_BASE_URL = "https://api.baserow.io"

# Baserow caps the row list page size at 200 (ERROR_PAGE_SIZE_LIMIT above it).
PAGE_SIZE = 200

# Row ids are unique within a table, and each Baserow table syncs into its own
# warehouse table, so the bare id is unique table-wide.
ROWS_PRIMARY_KEYS = ["id"]

REQUEST_TIMEOUT_SECONDS = 30.0
