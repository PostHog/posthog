from typing import Final

# Firestore and Identity Platform both expose a `v1` REST surface alongside older `v1beta*`
# channels; `v1` is the generally available one.
API_VERSION: Final = "v1"

FIRESTORE_API_ROOT: Final = f"https://firestore.googleapis.com/{API_VERSION}"
IDENTITY_TOOLKIT_API_ROOT: Final = f"https://identitytoolkit.googleapis.com/{API_VERSION}"
GOOGLE_TOKEN_URI: Final = "https://oauth2.googleapis.com/token"

# Scopes requested in the service-account assertion. Google mints a token for whatever a service
# account asks for; what it can actually read is decided by the IAM roles on the project, so
# asking for all three costs nothing and keeps one token usable across every surface.
OAUTH_SCOPES: Final = (
    "https://www.googleapis.com/auth/datastore "  # Cloud Firestore
    "https://www.googleapis.com/auth/firebase "  # Identity Platform / Firebase Auth
    "https://www.googleapis.com/auth/firebase.database "  # Realtime Database
    "https://www.googleapis.com/auth/userinfo.email"  # required alongside firebase.database
)

DEFAULT_DATABASE_ID: Final = "(default)"

AUTH_USERS_TABLE: Final = "auth_users"
FIRESTORE_TABLE_PREFIX: Final = "firestore_"
REALTIME_DATABASE_TABLE_PREFIX: Final = "realtime_database_"

# Firestore caps a `listDocuments` page at 300 documents; Identity Platform caps `accounts:batchGet`
# at 1000; the Realtime Database has no documented cap, so this is a memory choice.
FIRESTORE_PAGE_SIZE: Final = 300
FIRESTORE_COLLECTION_IDS_PAGE_SIZE: Final = 300
AUTH_USERS_PAGE_SIZE: Final = 1000
REALTIME_DATABASE_PAGE_SIZE: Final = 500

# Hard stop so an endpoint that keeps handing back a page token can't page forever.
MAX_PAGES: Final = 100_000

REQUEST_TIMEOUT_SECONDS: Final = 120

# Re-mint a little before Google's stated expiry so a long-running page fetch can't start with a
# token that expires mid-flight.
TOKEN_EXPIRY_SKEW_SECONDS: Final = 120
JWT_ASSERTION_LIFETIME_SECONDS: Final = 3600
JWT_GRANT_TYPE: Final = "urn:ietf:params:oauth:grant-type:jwt-bearer"

# Firestore documents are schemaless, so the sync adds its own metadata columns. The `_firestore_`
# prefix keeps them from colliding with a document field of the same name.
FIRESTORE_ID_COLUMN: Final = "_firestore_id"
FIRESTORE_PATH_COLUMN: Final = "_firestore_path"
FIRESTORE_CREATE_TIME_COLUMN: Final = "_firestore_create_time"
FIRESTORE_UPDATE_TIME_COLUMN: Final = "_firestore_update_time"

REALTIME_DATABASE_KEY_COLUMN: Final = "_realtime_database_key"
REALTIME_DATABASE_PATH_COLUMN: Final = "_realtime_database_path"
# Holds the child node when it is a scalar rather than an object.
REALTIME_DATABASE_VALUE_COLUMN: Final = "value"

AUTH_USERS_PRIMARY_KEY: Final = ["localId"]

# Password material Identity Platform returns to sufficiently privileged callers. Warehousing a
# password hash serves no analytics purpose, so it never leaves the source.
REDACTED_AUTH_USER_FIELDS: Final = frozenset({"passwordHash", "salt", "rawPassword"})

# The only hosts a Realtime Database lives on. Restricting to these stops a source edit from
# pointing the minted Google access token at an arbitrary server.
REALTIME_DATABASE_HOST_SUFFIXES: Final = (".firebaseio.com", ".firebasedatabase.app")


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
