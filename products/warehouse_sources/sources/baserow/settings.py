DEFAULT_BASE_URL = "https://api.baserow.io"

# Baserow caps the row list page size at 200 (ERROR_PAGE_SIZE_LIMIT above it).
PAGE_SIZE = 200

# Row ids are unique within a table, and each Baserow table syncs into its own
# warehouse table, so the bare id is unique table-wide.
ROWS_PRIMARY_KEYS = ["id"]

REQUEST_TIMEOUT_SECONDS = 30.0

# Split connect/read timeouts for the row-sync path: RESTClient.send() supplies no
# timeout, so without this a user-controlled host could accept the connection and then
# leave a row response unfinished, occupying an import worker until the resumable
# activity's week-long timeout.
CONNECT_TIMEOUT_SECONDS = 10.0
READ_TIMEOUT_SECONDS = 30.0

# Hard wall-clock ceiling on delivering a single response body. READ_TIMEOUT_SECONDS is only
# a socket-inactivity timeout: a host that drips a byte before each idle window keeps the read
# blocked indefinitely while staying under the byte cap. The body is read on a daemon thread
# that is abandoned past this deadline (closing the response to unblock the socket), so a
# slow-drip host can't monopolize an import worker. Generous for a legitimate page on a slow
# link while still bounding a stalled transfer.
READ_DEADLINE_SECONDS = 120.0

# Hard per-response cap on decoded body bytes. `requests` buffers and decodes the whole
# body before returning, so a hostile host could return an arbitrarily large — or highly
# compressed — page and exhaust a worker's memory. The body is streamed and decoded
# incrementally under this ceiling and aborted the instant it is crossed. Sized well above
# a legitimate 200-row page while still bounding a single response.
MAX_RESPONSE_BYTES = 100 * 1024 * 1024
# Compressed bytes pulled per streamed read while enforcing the cap; small so a
# decompression bomb can inflate at most one chunk's worth past the cap before we abort.
RESPONSE_READ_CHUNK_BYTES = 64 * 1024

# Coarse backstop on pages followed in a single sync run — far above any realistic Baserow
# table (200 rows/page), so it never bites a legitimate sync. Paired with the same-URL
# cycle guard in BaserowPaginator, it stops a host that returns an endless stream of
# distinct `next` URLs from keeping a resumable import running until its activity timeout.
MAX_PAGES_PER_SYNC = 1_000_000
