from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

StytchFanOut = Literal["users", "organizations"]


@dataclass
class StytchEndpointConfig:
    name: str
    path: str
    # Response field holding the rows (Stytch wraps them per endpoint: results/sessions/organizations/members).
    data_key: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field for datetime partitioning; never an updated-at style field.
    partition_key: Optional[str] = None
    should_sync_default: bool = True
    description: Optional[str] = None
    # "users": one GET per user enumerated via the users search (sessions).
    # "organizations": member search fanned out over organization_id chunks (members).
    fan_out: Optional[StytchFanOut] = None
    # B2B-only endpoints error on consumer (B2C) projects, so they must not be default-on.
    b2b_only: bool = False


STYTCH_ENDPOINTS: dict[str, StytchEndpointConfig] = {
    "users": StytchEndpointConfig(
        name="users",
        path="/v1/users/search",
        data_key="results",
        primary_keys=["user_id"],
        partition_key="created_at",
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        description=(
            "All users in the project with their auth methods (emails, phone numbers, OAuth providers, "
            "TOTPs, passkeys). Stytch exposes no updated-at filter, so incremental syncs only pick up "
            "newly created users; run a periodic full refresh to capture changes to existing users"
        ),
    ),
    "sessions": StytchEndpointConfig(
        name="sessions",
        path="/v1/sessions",
        data_key="sessions",
        primary_keys=["session_id"],
        fan_out="users",
        should_sync_default=False,
        description=(
            "Active sessions, fetched one request per user (expired sessions are not returned by the "
            "Stytch API). Off by default because of the per-user API cost on large projects"
        ),
    ),
    "organizations": StytchEndpointConfig(
        name="organizations",
        path="/v1/b2b/organizations/search",
        data_key="organizations",
        primary_keys=["organization_id"],
        should_sync_default=False,
        b2b_only=True,
        description="Organizations in a Stytch B2B project. Errors on consumer (B2C) projects",
    ),
    "members": StytchEndpointConfig(
        name="members",
        path="/v1/b2b/organizations/members/search",
        data_key="members",
        primary_keys=["member_id"],
        fan_out="organizations",
        should_sync_default=False,
        b2b_only=True,
        description="Members across all organizations in a Stytch B2B project. Errors on consumer (B2C) projects",
    ),
}

ENDPOINTS = tuple(STYTCH_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in STYTCH_ENDPOINTS.items()
}
