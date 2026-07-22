"""Freshchat source settings and endpoint catalog."""

from dataclasses import dataclass, field
from typing import Optional

# Freshchat caps `items_per_page` at 50 (default 20). Pull the max to keep the request
# count — and therefore rate-limit pressure — as low as possible.
PER_PAGE = 50

# The `GET /v2/users` list endpoint requires at least one filter parameter; a bare list
# request errors. `created_from` is a stable creation-time floor that lets us page every
# user without excluding anyone. This is a full-refresh floor, not an incremental cursor.
USERS_CREATED_FROM = "2000-01-01T00:00:00.000Z"


@dataclass
class FreshchatEndpointConfig:
    name: str
    # Path relative to the `/v2` base (e.g. `/agents`).
    path: str
    # Freshchat wraps most list responses in an object keyed by the resource name
    # (e.g. {"agents": [...], "pagination": {...}}); `data_key` is that key. The envelope is
    # inconsistent across the API, so the extractor also falls back to a bare array / single
    # object when the key is absent.
    data_key: Optional[str] = None
    # `True` for the paginated collection endpoints (page / items_per_page). `False` for
    # single-object endpoints like accounts/configuration.
    paginated: bool = True
    # `True` when the endpoint returns a single object rather than a collection — we wrap it
    # into a one-row list so it lands as a single warehouse row.
    single_object: bool = False
    # Extra static query params (e.g. the mandatory `created_from` filter on users).
    extra_params: dict[str, str] = field(default_factory=dict)


# Freshchat v2 top-level endpoints.
#
# The public REST API exposes no server-side updated_since / created_since cursor on these
# core list endpoints, so every endpoint is full refresh only (no `supports_incremental`).
# Pagination is resumable by page number via the ResumableSource manager. Conversations,
# messages and per-user conversation fan-out require object IDs (there is no top-level list
# endpoint for them) and are intentionally left out of this first cut; outbound-messages and
# the raw report endpoints require time-window params and are likewise deferred.
FRESHCHAT_ENDPOINTS: dict[str, FreshchatEndpointConfig] = {
    "agents": FreshchatEndpointConfig(
        name="agents",
        path="/agents",
        data_key="agents",
    ),
    "users": FreshchatEndpointConfig(
        name="users",
        path="/users",
        data_key="users",
        # At least one filter is mandatory on this endpoint; the created-time floor lists all users.
        extra_params={"created_from": USERS_CREATED_FROM},
    ),
    "groups": FreshchatEndpointConfig(
        name="groups",
        path="/groups",
        data_key="groups",
    ),
    "channels": FreshchatEndpointConfig(
        name="channels",
        path="/channels",
        data_key="channels",
    ),
    "accounts_configuration": FreshchatEndpointConfig(
        name="accounts_configuration",
        path="/accounts/configuration",
        data_key="configuration",
        paginated=False,
        single_object=True,
    ),
}

ENDPOINTS = tuple(FRESHCHAT_ENDPOINTS.keys())

# `id` is the auto-generated primary key on agents / users / groups / channels. The single
# account-configuration row is keyed on its stable Freshchat app id.
PRIMARY_KEYS: dict[str, list[str]] = {
    "agents": ["id"],
    "users": ["id"],
    "groups": ["id"],
    "channels": ["id"],
    "accounts_configuration": ["app_id"],
}
