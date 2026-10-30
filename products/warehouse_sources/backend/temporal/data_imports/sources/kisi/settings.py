from datetime import timedelta

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

BASE_URL = "https://api.kisi.io"
PAGE_SIZE = 100
MAX_OFFSET = 20_000

EVENTS = "events"
ROLES = "roles"
GROUPS = "groups"
GROUP_LOCKS = "group_locks"

ENDPOINTS = (
    "locks",
    "places",
    "users",
    GROUPS,
    "role_assignments",
    "controllers",
    "readers",
    ROLES,
    EVENTS,
    GROUP_LOCKS,
    "teams",
    "team_memberships",
)
PRIMARY_KEYS: dict[str, list[str]] = {EVENTS: ["uuid"]}
DEFAULT_PRIMARY_KEYS = ["id"]
# Roles have no creation timestamp to partition on.
PARTITION_KEYS: dict[str, list[str] | None] = {ROLES: None}
DEFAULT_PARTITION_KEYS = ["created_at"]
# Kisi returns every role in one response, with no pagination parameters.
UNPAGINATED_ENDPOINTS = (ROLES,)
# Kisi requires a group_id on every group locks request, so the table reads each group in turn.
GROUP_LOCKS_PATH = "group_locks?group_id={group_id}"

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    EVENTS: [
        IncrementalField(
            label="created_at",
            type=IncrementalFieldType.DateTime,
            field="created_at",
            field_type=IncrementalFieldType.DateTime,
        )
    ]
}
# Re-read the last hour on each incremental sync, so events that Kisi stores late still land.
EVENTS_INCREMENTAL_LOOKBACK_SECONDS = 3600

# Kisi rejects an event set interval wider than 90 days.
EVENTS_WINDOW = timedelta(days=90)
# Kisi keeps events according to the organization's retention policy. A window older than that is empty and costs one request.
EVENTS_INITIAL_LOOKBACK = timedelta(days=730)
EVENTS_POLL_INTERVAL_SECONDS = 2.0
EVENTS_POLL_MAX_ATTEMPTS = 150
# Kisi allows one event set creation per second.
EVENTS_CREATE_INTERVAL_SECONDS = 1.0
EVENTS_MAX_PAGES_PER_WINDOW = 100_000

AUTH_ERROR = "Kisi rejected the API key. Create a new key in My Account > API and reconnect."
PERMISSION_ERROR = "The Kisi API key cannot read this resource. Check the account permissions in Kisi."
OFFSET_ERROR = "Kisi's pagination limit prevents a complete import. Contact Kisi support for an export of this table."
EVENT_SET_FAILED_ERROR = "Kisi could not prepare the events for export. Try the sync again later."
EVENT_SET_TIMEOUT_ERROR = "Kisi did not finish preparing the events for export in time."
EVENT_SET_EXPIRED_ERROR = "Kisi expired the event export before the sync read it."
EVENT_SET_CURSOR_ERROR = "Kisi repeated an event page cursor, so the events sync stopped to avoid a loop."
