from products.warehouse_sources.sources.sdk import IncrementalFieldType

# Cloudflare serves the catalog and the R2 storage under this domain. The API token only goes to it.
CLOUDFLARE_STORAGE_DOMAIN = "cloudflarestorage.com"
R2_STORAGE_DOMAIN = "r2.cloudflarestorage.com"
DEFAULT_CATALOG_HOST = "catalog.cloudflarestorage.com"

# (connect, read) seconds for one catalog or storage request.
REQUEST_TIMEOUT = (10, 120)
# Bytes of a Parquet file that stay in memory before the download spills to a temporary file.
SPOOL_MEMORY_BYTES = 64 * 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
BATCH_ROWS = 5_000
# A data file is read whole before parsing. Compaction writes 128 MiB files by default, so this only stops outliers.
MAX_DATA_FILE_BYTES = 4 * 1024 * 1024 * 1024
DOWNLOAD_DEADLINE_SECONDS = 30 * 60
# A long download reaches a safe point after each of these many bytes, so a worker shutdown can hand the run over.
DOWNLOAD_SAFE_POINT_BYTES = 64 * 1024 * 1024

# Discovery loads every table once, inside a web request, so a catalog with more tables than this lists only the
# first ones. A sync loads its table by name and has no cap.
MAX_DISCOVERED_TABLES = 1_000
MAX_DISCOVERED_NAMESPACES = 1_000
DISCOVERY_CONCURRENCY = 8
MAX_NAMESPACE_DEPTH = 8

# Vended credentials without an expiry are renewed after this many seconds.
DEFAULT_CREDENTIAL_LIFETIME_SECONDS = 30 * 60
CREDENTIAL_REFRESH_MARGIN_SECONDS = 5 * 60

ACCESS_DELEGATION_HEADER = "X-Iceberg-Access-Delegation"
VENDED_CREDENTIALS = "vended-credentials"

# Iceberg primitive types that work as an incremental cursor, and how the UI shows them.
INCREMENTAL_TYPES: dict[str, IncrementalFieldType] = {
    "int": IncrementalFieldType.Integer,
    "long": IncrementalFieldType.Integer,
    "date": IncrementalFieldType.Date,
    "timestamp": IncrementalFieldType.DateTime,
    "timestamptz": IncrementalFieldType.DateTime,
    "timestamp_ns": IncrementalFieldType.DateTime,
    "timestamptz_ns": IncrementalFieldType.DateTime,
}
