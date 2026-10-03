from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

CLEVER_BASE_URL = "https://api.clever.com/v3.0"

# Clever's documented maximum page size (the default is 100 if omitted); requesting the max
# means fewer round trips for a full district roster sync.
CLEVER_PAGE_SIZE = 10000

# Clever's event ids are ObjectIDs returned oldest-to-newest by /events, so the id itself
# doubles as a stable incremental cursor for that endpoint (see clever.py).
_EVENTS_INCREMENTAL_FIELD = "id"


@frozen
class CleverEndpointConfig:
    name: str
    path: str
    extra_params: dict[str, str] = field(default_factory=dict)
    incremental: bool = False
    # Stable creation timestamp to partition on. Left unset for endpoints whose object has no
    # `created`/`last_modified` field (Districts, Courses, Terms), per Clever's data model docs.
    partition_key: Optional[str] = None

    @property
    def incremental_fields(self) -> list[IncrementalField]:
        if not self.incremental:
            return []
        return [
            {
                "label": _EVENTS_INCREMENTAL_FIELD,
                "type": IncrementalFieldType.ObjectID,
                "field": _EVENTS_INCREMENTAL_FIELD,
                "field_type": IncrementalFieldType.ObjectID,
            }
        ]


CLEVER_ENDPOINTS: dict[str, CleverEndpointConfig] = {
    "Districts": CleverEndpointConfig(name="Districts", path="/districts"),
    "Schools": CleverEndpointConfig(name="Schools", path="/schools", partition_key="created"),
    "Users": CleverEndpointConfig(name="Users", path="/users", partition_key="created"),
    "Sections": CleverEndpointConfig(name="Sections", path="/sections", partition_key="created"),
    "Courses": CleverEndpointConfig(name="Courses", path="/courses"),
    "Terms": CleverEndpointConfig(name="Terms", path="/terms"),
    # Clever has no dedicated contacts/guardians endpoint - they're users with the `contact`
    # role, listed via the documented `role` filter on /users.
    "Contacts": CleverEndpointConfig(
        name="Contacts", path="/users", extra_params={"role": "contact"}, partition_key="created"
    ),
    # Delta feed of created/updated/deleted events across every record type. Clever retains
    # only 30 days of events, so a sync gap longer than that needs a full re-sync of the
    # entity endpoints above to catch up.
    "Events": CleverEndpointConfig(name="Events", path="/events", incremental=True, partition_key="created"),
}

ENDPOINTS = tuple(CLEVER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CLEVER_ENDPOINTS.items()
}
