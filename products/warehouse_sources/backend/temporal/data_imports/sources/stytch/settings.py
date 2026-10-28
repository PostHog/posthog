from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

StytchFanOut = Literal["users", "organizations", "organization", "member"]


@dataclass(frozen=True)
class StytchEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    # Response field holding the rows (Stytch wraps them per endpoint: results/sessions/organizations/members).
    # Empty for rbac_policy and sso_connections, whose rows span several response fields.
    data_key: str = ""
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field for datetime partitioning; never an updated-at style field.
    partition_key: Optional[str] = None
    should_sync_default: bool = True
    description: Optional[str] = None
    # "users": one GET per user enumerated via the users search (sessions).
    # "organizations": member search fanned out over organization_id chunks (members).
    # "organization": one GET per organization, with `{organization_id}` in the path.
    # "member": one GET per member, enumerated via the chunked member search.
    fan_out: Optional[StytchFanOut] = None
    # B2B-only endpoints error on consumer (B2C) projects, so they must not be default-on.
    b2b_only: bool = False
    # Served by both consumer and B2B projects, so the schema picker never flags it.
    any_product_line: bool = False


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
    "rbac_policy": StytchEndpointConfig(
        name="rbac_policy",
        # Consumer projects answer the B2B path with invalid_b2b_endpoint; the transport then reads /v1/rbac/policy.
        path="/v1/b2b/rbac/policy",
        primary_keys=["entry_type", "entry_id"],
        should_sync_default=False,
        any_product_line=True,
        description=(
            "The project's RBAC policy, one row per role, resource and scope (entry_type tells them apart). "
            "Resolves the role IDs on members and the scopes granted to connected apps"
        ),
    ),
    "sso_connections": StytchEndpointConfig(
        name="sso_connections",
        path="/v1/b2b/sso/{organization_id}",
        primary_keys=["connection_id"],
        fan_out="organization",
        should_sync_default=False,
        b2b_only=True,
        description=(
            "SAML, OIDC and external SSO connections of every organization, fetched one request per "
            "organization. OIDC client secrets and SAML encryption private keys are not synced. "
            "Errors on consumer (B2C) projects"
        ),
    ),
    "organization_connected_apps": StytchEndpointConfig(
        name="organization_connected_apps",
        path="/v1/b2b/organizations/{organization_id}/connected_apps",
        data_key="connected_apps",
        primary_keys=["organization_id", "connected_app_id"],
        fan_out="organization",
        should_sync_default=False,
        b2b_only=True,
        description=(
            "Connected apps that members of each organization have authorized, fetched one request per "
            "organization. Errors on consumer (B2C) projects"
        ),
    ),
    "member_connected_apps": StytchEndpointConfig(
        name="member_connected_apps",
        path="/v1/b2b/organizations/{organization_id}/members/{member_id}/connected_apps",
        data_key="connected_apps",
        primary_keys=["member_id", "connected_app_id"],
        fan_out="member",
        should_sync_default=False,
        b2b_only=True,
        description=(
            "Connected apps each member has authorized, with the scopes granted. Fetched one request per "
            "member, so it is off by default because of the API cost on large projects. Errors on consumer "
            "(B2C) projects"
        ),
    ),
}

ENDPOINTS = tuple(STYTCH_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in STYTCH_ENDPOINTS.items()
}
