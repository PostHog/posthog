from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# UserVoice caps `per_page` at 100 on its Admin API v2 list actions (default 20). Always request the
# max to minimise round trips.
PER_PAGE = 100


def _updated_at_incremental_fields() -> list[IncrementalField]:
    # UserVoice's only server-side time filter is `updated_after`, which keys off `updated_at`.
    # Advertising just `updated_at` keeps the user's chosen cursor aligned with what the API filters on.
    return [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


@dataclass
class UservoiceEndpointConfig:
    name: str
    # Path under /api/v2/admin, e.g. "/suggestions".
    path: str
    # Root key of the list in the JSON response. UserVoice wraps each list under its plural resource
    # name (e.g. {"suggestions": [...], "pagination": {...}}), which equals `path` minus the slash.
    response_key: str
    # UserVoice documents `updated_after` (filters by `updated_at`) on every GET list action. We only
    # turn it on for the mutable, high-volume resources; the small config-like tables sync full refresh.
    supports_incremental: bool
    # Stable creation-time field to partition by. Every UserVoice object carries `created_at`.
    partition_key: Optional[str] = "created_at"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True


# Endpoint catalog for the UserVoice Admin API v2. The helpdesk resources (tickets, ticket_messages)
# only return data on accounts with the Helpdesk feature enabled; users who don't have it simply leave
# those tables deselected.
USERVOICE_ENDPOINTS: dict[str, UservoiceEndpointConfig] = {
    "suggestions": UservoiceEndpointConfig(
        name="suggestions",
        path="/suggestions",
        response_key="suggestions",
        supports_incremental=True,
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "forums": UservoiceEndpointConfig(
        name="forums",
        path="/forums",
        response_key="forums",
        supports_incremental=True,
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "users": UservoiceEndpointConfig(
        name="users",
        path="/users",
        response_key="users",
        supports_incremental=True,
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "comments": UservoiceEndpointConfig(
        name="comments",
        path="/comments",
        response_key="comments",
        supports_incremental=True,
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "notes": UservoiceEndpointConfig(
        name="notes",
        path="/notes",
        response_key="notes",
        supports_incremental=True,
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "nps_ratings": UservoiceEndpointConfig(
        name="nps_ratings",
        path="/nps_ratings",
        response_key="nps_ratings",
        supports_incremental=True,
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "tickets": UservoiceEndpointConfig(
        name="tickets",
        path="/tickets",
        response_key="tickets",
        supports_incremental=True,
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "ticket_messages": UservoiceEndpointConfig(
        name="ticket_messages",
        path="/ticket_messages",
        response_key="ticket_messages",
        supports_incremental=True,
        incremental_fields=_updated_at_incremental_fields(),
    ),
    # Small, config-like reference tables — cheap to pull in full every run, so no incremental filter.
    "suggestion_statuses": UservoiceEndpointConfig(
        name="suggestion_statuses",
        path="/suggestion_statuses",
        response_key="suggestion_statuses",
        supports_incremental=False,
    ),
    "labels": UservoiceEndpointConfig(
        name="labels",
        path="/labels",
        response_key="labels",
        supports_incremental=False,
    ),
}

ENDPOINTS = tuple(USERVOICE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in USERVOICE_ENDPOINTS.items()
}
