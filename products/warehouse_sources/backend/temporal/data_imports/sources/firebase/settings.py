from typing import Final

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
REALTIME_DATABASE_TABLE_PREFIX: Final[str] = "realtime_database_"

# Firestore caps a `listDocuments` page at 300 documents; Identity Platform caps `accounts:batchGet`
# at 1000; the Realtime Database has no documented cap, so this is a memory choice.
FIRESTORE_PAGE_SIZE: Final[int] = 300
FIRESTORE_COLLECTION_IDS_PAGE_SIZE: Final[int] = 300
AUTH_USERS_PAGE_SIZE: Final[int] = 1000
REALTIME_DATABASE_PAGE_SIZE: Final[int] = 500

# Hard stop so an endpoint that keeps handing back a page token can't page forever.
MAX_PAGES: Final[int] = 100_000

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

REALTIME_DATABASE_KEY_COLUMN: Final[str] = "_realtime_database_key"
REALTIME_DATABASE_PATH_COLUMN: Final[str] = "_realtime_database_path"
# Holds the child node when it is a scalar rather than an object.
REALTIME_DATABASE_VALUE_COLUMN: Final[str] = "value"

AUTH_USERS_PRIMARY_KEY: Final[list[str]] = ["localId"]

# Password material Identity Platform returns to sufficiently privileged callers. Warehousing a
# password hash serves no analytics purpose, so it never leaves the source.
REDACTED_AUTH_USER_FIELDS: Final[frozenset[str]] = frozenset({"passwordHash", "salt", "rawPassword"})

# The only hosts a Realtime Database lives on. Restricting to these stops a source edit from
# pointing the minted Google access token at an arbitrary server.
REALTIME_DATABASE_HOST_SUFFIXES: Final[tuple[str, ...]] = (".firebaseio.com", ".firebasedatabase.app")


def firestore_table_name(collection_id: str) -> str:
    return f"{FIRESTORE_TABLE_PREFIX}{collection_id}"


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
