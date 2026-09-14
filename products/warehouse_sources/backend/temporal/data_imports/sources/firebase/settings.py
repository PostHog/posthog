import re
from typing import Final

from products.warehouse_sources.backend.types import IncrementalFieldType

# Firestore and Identity Platform both expose a `v1` REST surface alongside older `v1beta*`
# channels; `v1` is the generally available one.
API_VERSION: Final[str] = "v1"

FIRESTORE_API_ROOT: Final[str] = f"https://firestore.googleapis.com/{API_VERSION}"
IDENTITY_TOOLKIT_API_ROOT: Final[str] = f"https://identitytoolkit.googleapis.com/{API_VERSION}"
GOOGLE_TOKEN_URI: Final[str] = "https://oauth2.googleapis.com/token"

# Scopes requested in the service-account assertion. Google mints a token for whatever a service
# account asks for; what it can actually read is decided by the IAM roles on the project, so
# asking for all three costs nothing and keeps one token usable across every surface.
OAUTH_SCOPES: Final[str] = (
    "https://www.googleapis.com/auth/datastore "  # Cloud Firestore
    "https://www.googleapis.com/auth/firebase "  # Identity Platform / Firebase Auth
    "https://www.googleapis.com/auth/firebase.database "  # Realtime Database
    "https://www.googleapis.com/auth/userinfo.email"  # required alongside firebase.database
)

DEFAULT_DATABASE_ID: Final[str] = "(default)"

AUTH_USERS_TABLE: Final[str] = "auth_users"
FIRESTORE_TABLE_PREFIX: Final[str] = "firestore_"
# A subcollection reads as a collection group (every collection with the id, under any parent). The
# `/` in the prefix states that scope and cannot appear in a Firestore collection id, so no root
# collection can ever produce this name and be routed to the wrong reader.
FIRESTORE_COLLECTION_GROUP_TABLE_PREFIX: Final[str] = "firestore_collection_group/"
REALTIME_DATABASE_TABLE_PREFIX: Final[str] = "realtime_database_"

# Firestore caps a `listDocuments` page at 300 documents; Identity Platform caps `accounts:batchGet`
# at 1000; the Realtime Database has no documented cap, so this is a memory choice.
FIRESTORE_PAGE_SIZE: Final[int] = 300
FIRESTORE_COLLECTION_IDS_PAGE_SIZE: Final[int] = 300
AUTH_USERS_PAGE_SIZE: Final[int] = 1000
REALTIME_DATABASE_PAGE_SIZE: Final[int] = 500

# Firestore has no API to list a collection's subcollections, only a single document's. So table
# discovery samples a few documents per collection and unions the subcollection ids they report.
# A subcollection present on no sampled document is missed. `depth` bounds how far nesting is
# followed below the root collections.
FIRESTORE_SUBCOLLECTION_SAMPLE_DOCUMENTS: Final[int] = 10
FIRESTORE_MAX_SUBCOLLECTION_DEPTH: Final[int] = 3

# Discovery walks the project one document sample at a time, so it can fire ~11 sequential requests
# per collection id — all on the synchronous schema-lookup path a user waits on. Cache the result so
# repeated lookups don't repeat the walk; the user-triggered refresh bypasses it. Mirrors the Slack
# source's channel-discovery cache, which caps the same cost for the same reason.
FIRESTORE_DISCOVERY_CACHE_TTL_SECONDS: Final[int] = 300

# Hard stop so an endpoint that keeps handing back a page token can't page forever.
MAX_PAGES: Final[int] = 100_000

# `get_incremental_fields` samples one collection at a time, synchronously, to build the cursor-field
# picker. The `names` filter already bounds this to the handful of tables a sync-settings request asks
# about, but a first-time "list every table" request passes every collection in the project, and
# `MAX_PAGES` lets that list run into the hundreds of thousands. Past this many collections, the
# remainder still gets listed as a table but is offered full refresh only, rather than tying up a
# worker sampling collections one HTTP request at a time.
FIRESTORE_INCREMENTAL_DISCOVERY_LIMIT: Final[int] = 200

REQUEST_TIMEOUT_SECONDS: Final[int] = 120

# Byte caps on response bodies. The page sizes above bound the row count but not the byte count —
# a Firestore document may be 1 MiB and the Realtime Database documents no page ceiling at all — so
# without these a single page could buffer hundreds of MiB in a shared worker before `json.loads`
# builds a second, larger representation of it. The caps apply to the *decompressed* body, so a
# compressed payload can't expand past them either.
#
# 64 MiB sits far above any realistic page (300 Firestore documents at a typical few KiB each is
# single-digit MiB) while still bounding the spike. Token and error bodies are small and
# well-known, so they get much tighter caps.
MAX_RESPONSE_BYTES: Final[int] = 64 * 1024 * 1024
MAX_TOKEN_RESPONSE_BYTES: Final[int] = 256 * 1024
MAX_ERROR_BODY_BYTES: Final[int] = 64 * 1024

# Re-fetching the same page returns the same oversized body, so this never becomes retryable.
RESPONSE_TOO_LARGE_ERROR: Final[str] = "Firebase returned an oversized response body"

# Re-mint a little before Google's stated expiry so a long-running page fetch can't start with a
# token that expires mid-flight.
TOKEN_EXPIRY_SKEW_SECONDS: Final[int] = 120
JWT_ASSERTION_LIFETIME_SECONDS: Final[int] = 3600
JWT_GRANT_TYPE: Final[str] = "urn:ietf:params:oauth:grant-type:jwt-bearer"

# Firestore documents are schemaless, so the sync adds its own metadata columns. The `_firestore_`
# prefix keeps them from colliding with a document field of the same name.
FIRESTORE_ID_COLUMN: Final[str] = "_firestore_id"
FIRESTORE_PATH_COLUMN: Final[str] = "_firestore_path"
FIRESTORE_CREATE_TIME_COLUMN: Final[str] = "_firestore_create_time"
FIRESTORE_UPDATE_TIME_COLUMN: Final[str] = "_firestore_update_time"
FIRESTORE_METADATA_COLUMNS: Final[frozenset[str]] = frozenset(
    {FIRESTORE_ID_COLUMN, FIRESTORE_PATH_COLUMN, FIRESTORE_CREATE_TIME_COLUMN, FIRESTORE_UPDATE_TIME_COLUMN}
)

REALTIME_DATABASE_KEY_COLUMN: Final[str] = "_realtime_database_key"
REALTIME_DATABASE_PATH_COLUMN: Final[str] = "_realtime_database_path"
# Holds the child node when it is a scalar rather than an object.
REALTIME_DATABASE_VALUE_COLUMN: Final[str] = "value"

AUTH_USERS_PRIMARY_KEY: Final[list[str]] = ["localId"]

# Firestore stores no schema, so the cursor fields a collection can offer are read off a sample of
# real documents. Ten is enough to reject a field that only some documents carry, while keeping
# discovery to one extra request per collection.
FIRESTORE_SCHEMA_SAMPLE_DOCUMENTS: Final[int] = 10

# Value types a Firestore field can hold and still order a collection, mapped to the cursor type the
# pipeline tracks. A field holding an ISO-8601 *string* is deliberately absent: Firestore compares
# strings byte by byte, and Firestore's own timestamps render with a variable number of fractional
# digits, so `2026-01-01T00:00:00Z` sorts after `2026-01-01T00:00:00.5Z` and rows get skipped.
FIRESTORE_INCREMENTAL_VALUE_TYPES: Final[dict[str, IncrementalFieldType]] = {
    "timestampValue": IncrementalFieldType.DateTime,
    "integerValue": IncrementalFieldType.Integer,
}

# Firestore orders values by type before value, so a lone `field > cursor` bound also matches every
# value that sorts above the cursor's type: strings, arrays, maps. An upper bound of the cursor's own
# type confines the read to one type band. Without it a collection whose field is a timestamp in most
# documents and a string in one would return that string on every run, and it would then become the
# watermark, which no later timestamp can beat.
# https://firebase.google.com/docs/firestore/manage-data/data-types
FIRESTORE_MAX_TIMESTAMP: Final[str] = "9999-12-31T23:59:59.999999999Z"
FIRESTORE_MAX_INTEGER: Final[int] = 2**63 - 1

# The reserved field path for a document's own id. Ordering by it after the cursor field keeps paging
# stable when several documents share one cursor value.
FIRESTORE_DOCUMENT_ID_FIELD: Final[str] = "__name__"

# A field path segment Firestore reads without backtick quoting. A document field name may hold dots
# and other punctuation, which a field path would read as a path into a nested map, so a field whose
# name needs quoting is never offered as a cursor rather than risking a read of the wrong field.
_UNQUOTED_FIELD_PATH = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Firestore answers a query it holds no index for with FAILED_PRECONDITION and a console URL that
# builds the index in one click. Building it takes minutes, so no retry recovers within a job.
FIRESTORE_INDEX_REQUIRED_ERROR: Final[str] = "The query requires an index"

# Password material Identity Platform returns to sufficiently privileged callers. Warehousing a
# password hash serves no analytics purpose, so it never leaves the source.
REDACTED_AUTH_USER_FIELDS: Final[frozenset[str]] = frozenset({"passwordHash", "salt", "rawPassword"})

# The only hosts a Realtime Database lives on. Restricting to these stops a source edit from
# pointing the minted Google access token at an arbitrary server.
REALTIME_DATABASE_HOST_SUFFIXES: Final[tuple[str, ...]] = (".firebaseio.com", ".firebasedatabase.app")


def firestore_table_name(collection_id: str) -> str:
    """Table name for one root-level Firestore collection (`rooms`)."""
    return f"{FIRESTORE_TABLE_PREFIX}{collection_id}"


def firestore_collection_group_table_name(collection_id: str) -> str:
    """Table name for one Firestore subcollection, read as a collection group keyed by its id."""
    return f"{FIRESTORE_COLLECTION_GROUP_TABLE_PREFIX}{collection_id}"


def is_supported_incremental_field_name(name: str) -> bool:
    return bool(_UNQUOTED_FIELD_PATH.match(name))


def realtime_database_table_name(path: str) -> str:
    """Table name for one Realtime Database path. `rooms/lobby` becomes `..._rooms_lobby`."""
    return f"{REALTIME_DATABASE_TABLE_PREFIX}{path.strip('/').replace('/', '_')}"


def parse_realtime_database_paths(raw: str | None) -> list[str]:
    """Split the comma-separated path list from the source form, dropping blanks and slashes."""
    if not raw:
        return []
    seen: list[str] = []
    for candidate in raw.split(","):
        path = candidate.strip().strip("/")
        if path and path not in seen:
            seen.append(path)
    return seen
