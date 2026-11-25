from dataclasses import dataclass, field
from typing import Any, Literal

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, IncrementalFieldType


@dataclass(frozen=True)
class WorkOSEndpointConfig:
    name: str
    path: str
    # `created_at` is set once and never changes, so it's a stable partition key.
    partition_key: str = "created_at"
    page_size: int = 100  # WorkOS max page size
    # False for a list that WorkOS returns whole and that documents no `limit` or `order`.
    paginated: bool = True
    # Empty for a list whose order is fixed, such as the oldest-first events stream.
    order: str | None = "desc"
    params: dict[str, Any] = field(default_factory=dict)
    # Columns removed from each row, such as a secret that WorkOS returns in the object.
    excluded_fields: tuple[str, ...] = ()
    fanout: DependentEndpointConfig | None = None
    # Only `events` has a server-side timestamp filter (`range_start`).
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    sort_mode: Literal["asc"] | None = None


# The events list refuses a request without an `events` type filter, and WorkOS has no wildcard.
# These are the documented types of the identity data that the other tables hold. Vault, Pipes,
# feature flag, Radar and agent registration events are left out.
EVENT_TYPES: tuple[str, ...] = (
    "api_key.created",
    "api_key.revoked",
    "api_key.updated",
    "authentication.email_verification_failed",
    "authentication.email_verification_succeeded",
    "authentication.magic_auth_failed",
    "authentication.magic_auth_succeeded",
    "authentication.mfa_failed",
    "authentication.mfa_succeeded",
    "authentication.oauth_failed",
    "authentication.oauth_succeeded",
    "authentication.passkey_failed",
    "authentication.passkey_succeeded",
    "authentication.password_failed",
    "authentication.password_succeeded",
    "authentication.radar_risk_detected",
    "authentication.sso_failed",
    "authentication.sso_started",
    "authentication.sso_succeeded",
    "connection.activated",
    "connection.deactivated",
    "connection.deleted",
    "connection.saml_certificate_renewal_required",
    "connection.saml_certificate_renewed",
    "dsync.activated",
    "dsync.deleted",
    "dsync.group.created",
    "dsync.group.deleted",
    "dsync.group.updated",
    "dsync.group.user_added",
    "dsync.group.user_removed",
    "dsync.user.created",
    "dsync.user.deleted",
    "dsync.user.updated",
    "email_verification.created",
    "group.created",
    "group.deleted",
    "group.member_added",
    "group.member_removed",
    "group.updated",
    "invitation.accepted",
    "invitation.created",
    "invitation.resent",
    "invitation.revoked",
    "magic_auth.created",
    "organization.created",
    "organization.deleted",
    "organization.updated",
    "organization_domain.created",
    "organization_domain.deleted",
    "organization_domain.updated",
    "organization_domain.verification_failed",
    "organization_domain.verified",
    "organization_membership.created",
    "organization_membership.deleted",
    "organization_membership.updated",
    "organization_role.created",
    "organization_role.deleted",
    "organization_role.updated",
    "password_reset.created",
    "password_reset.succeeded",
    "permission.created",
    "permission.deleted",
    "permission.updated",
    "role.created",
    "role.deleted",
    "role.updated",
    "session.created",
    "session.revoked",
    "user.created",
    "user.deleted",
    "user.updated",
)

_CREATED_AT_INCREMENTAL: list[IncrementalField] = [
    {
        "label": "created_at",
        "type": IncrementalFieldType.DateTime,
        "field": "created_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]


# Parent of the `waitlist_entries` fan-out, not a table of its own. WorkOS returns every
# waitlist in one response and documents no `limit` param for it.
WAITLISTS_PARENT = WorkOSEndpointConfig(name="waitlists", path="/user_management/waitlists")


# WorkOS list endpoints share one cursor-paginated envelope
# ({"data": [...], "list_metadata": {"before": ..., "after": ...}}) and expose no
# server-side timestamp filter, so a polled sync is a full refresh. Only `events` syncs
# incrementally. WEBHOOK_EVENTS_BY_SCHEMA below lists the tables that leave polling behind.
WORKOS_ENDPOINTS: dict[str, WorkOSEndpointConfig] = {
    "organizations": WorkOSEndpointConfig(name="organizations", path="/organizations"),
    "users": WorkOSEndpointConfig(name="users", path="/user_management/users"),
    "connections": WorkOSEndpointConfig(name="connections", path="/connections"),
    "directories": WorkOSEndpointConfig(name="directories", path="/directories"),
    "directory_users": WorkOSEndpointConfig(name="directory_users", path="/directory_users"),
    "directory_groups": WorkOSEndpointConfig(name="directory_groups", path="/directory_groups"),
    "waitlist_entries": WorkOSEndpointConfig(
        name="waitlist_entries",
        path="/user_management/waitlists/{waitlist_id}/entries",
        fanout=DependentEndpointConfig(
            parent_name=WAITLISTS_PARENT.name,
            resolve_param="waitlist_id",
            resolve_field="id",
            # Entries already carry their own `waitlist_id`.
            include_from_parent=[],
            child_params={"limit": 100, "order": "desc"},
        ),
    ),
    # The list call refuses a request with neither `user_id` nor `organization_id`, so it fans out
    # over organizations. WorkOS returns only active memberships unless `statuses` asks for more,
    # and its SDKs send the list as one comma-joined value.
    "organization_memberships": WorkOSEndpointConfig(
        name="organization_memberships",
        path="/user_management/organization_memberships?organization_id={organization_id}",
        fanout=DependentEndpointConfig(
            parent_name="organizations",
            resolve_param="organization_id",
            resolve_field="id",
            # Memberships already carry their own `organization_id`.
            include_from_parent=[],
            parent_params={"limit": 100, "order": "desc"},
            child_params={"limit": 100, "order": "desc", "statuses": "active,inactive,pending"},
        ),
    ),
    # `token` and `accept_invitation_url` let anyone who holds them accept the invite.
    "invitations": WorkOSEndpointConfig(
        name="invitations",
        path="/user_management/invitations",
        excluded_fields=("token", "accept_invitation_url"),
    ),
    "roles": WorkOSEndpointConfig(name="roles", path="/authorization/roles", paginated=False, order=None),
    "organization_groups": WorkOSEndpointConfig(
        name="organization_groups",
        path="/organizations/{organization_id}/groups",
        fanout=DependentEndpointConfig(
            parent_name="organizations",
            resolve_param="organization_id",
            resolve_field="id",
            # Groups already carry their own `organization_id`.
            include_from_parent=[],
            parent_params={"limit": 100, "order": "desc"},
            child_params={"limit": 100, "order": "desc"},
        ),
    ),
    # WorkOS returns events oldest first and keeps them for 90 days. `range_start` and `after`
    # are mutually exclusive, so `range_start` goes on the first request only.
    "events": WorkOSEndpointConfig(
        name="events",
        path="/events",
        order=None,
        params={"events": ",".join(EVENT_TYPES)},
        incremental_fields=_CREATED_AT_INCREMENTAL,
        default_incremental_field="created_at",
        sort_mode="asc",
    ),
}

ENDPOINTS = tuple(WORKOS_ENDPOINTS.keys())

# Webhook sync replaces polling, so a table only qualifies when its events cover the whole
# create, update, and delete cycle. WorkOS publishes no `connection.updated` or `dsync.updated`
# event, which is why `connections` and `directories` stay on full refresh: under webhook sync a
# directory rename or a SAML certificate renewal would never reach the table.
WEBHOOK_EVENTS_BY_SCHEMA: dict[str, tuple[str, ...]] = {
    "users": ("user.created", "user.updated", "user.deleted"),
    "organizations": ("organization.created", "organization.updated", "organization.deleted"),
    "directory_users": ("dsync.user.created", "dsync.user.updated", "dsync.user.deleted"),
    "directory_groups": ("dsync.group.created", "dsync.group.updated", "dsync.group.deleted"),
}

WEBHOOK_EVENT_TO_SCHEMA = {event: schema for schema, events in WEBHOOK_EVENTS_BY_SCHEMA.items() for event in events}
WEBHOOK_SCHEMA_NAMES = frozenset(WEBHOOK_EVENTS_BY_SCHEMA)
ALL_WEBHOOK_EVENTS = tuple(event for events in WEBHOOK_EVENTS_BY_SCHEMA.values() for event in events)
