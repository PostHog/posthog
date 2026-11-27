"""Canonical, documentation-sourced descriptions for WorkOS endpoints and columns.

Sourced from the official WorkOS API reference (https://workos.com/docs/reference). Keyed by the
endpoint names in `settings.py` `WORKOS_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced WorkOS table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.sources.sdk import CanonicalDescriptions

# Fields shared by most WorkOS objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "object": "String describing the object's WorkOS type.",
    "created_at": "Time at which the object was created.",
    "updated_at": "Time at which the object was last updated.",
}


# PostHog adds these columns to the tables that can sync by webhook, because a webhook delete
# merges on `id` and can only mark a row, never remove it. WorkOS itself does not send them.
# The tables that get them are the keys of WEBHOOK_EVENTS_BY_SCHEMA in `settings.py`.
_TOMBSTONE_COLUMNS = {
    "workos_deleted": "Whether WorkOS reported this record as deleted. Added by PostHog, not a WorkOS field.",
    "workos_deleted_at": "Time at which WorkOS reported the delete. Null while the record still exists.",
}


def _columns(*, webhook_synced: bool = False, **overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **(_TOMBSTONE_COLUMNS if webhook_synced else {}), **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "organizations": {
        "description": "An organization (a tenant/company) in WorkOS that users and connections belong to.",
        "docs_url": "https://workos.com/docs/reference/organization",
        "columns": _columns(
            webhook_synced=True,
            name="The organization's display name.",
            domains="Verified domains associated with the organization.",
            allow_profiles_outside_organization="Whether users outside the organization's domains may sign in.",
        ),
    },
    "users": {
        "description": "A user managed by WorkOS User Management (AuthKit).",
        "docs_url": "https://workos.com/docs/reference/user-management/user",
        "columns": _columns(
            webhook_synced=True,
            email="The user's email address.",
            first_name="The user's first name.",
            last_name="The user's last name.",
            email_verified="Whether the user's email address has been verified.",
            profile_picture_url="URL of the user's profile picture.",
            last_sign_in_at="Time at which the user last signed in.",
        ),
    },
    "connections": {
        "description": "An SSO connection between an organization and an identity provider.",
        "docs_url": "https://workos.com/docs/reference/sso/connection",
        "columns": _columns(
            name="Name of the connection.",
            organization_id="ID of the organization the connection belongs to.",
            connection_type="Type of identity provider for the connection (e.g. OktaSAML, GoogleOAuth).",
            state="State of the connection (e.g. active, inactive).",
        ),
    },
    "directories": {
        "description": "A directory connection used for Directory Sync (SCIM) with an organization.",
        "docs_url": "https://workos.com/docs/reference/directory-sync/directory",
        "columns": _columns(
            name="Name of the directory.",
            organization_id="ID of the organization the directory belongs to.",
            domain="Primary domain associated with the directory.",
            type="Type of the directory provider (e.g. okta scim v2.0, azure scim v2.0).",
            state="State of the directory (e.g. linked, unlinked).",
        ),
    },
    "directory_users": {
        "description": "A user synced from an organization's directory via Directory Sync.",
        "docs_url": "https://workos.com/docs/reference/directory-sync/directory-user",
        "columns": _columns(
            webhook_synced=True,
            directory_id="ID of the directory the user was synced from.",
            organization_id="ID of the organization the directory belongs to.",
            email="The user's primary email address.",
            first_name="The user's first name.",
            last_name="The user's last name.",
            username="The user's username in the directory.",
            state="State of the user in the directory (active or inactive).",
            groups="Directory groups the user is a member of.",
        ),
    },
    "directory_groups": {
        "description": "A group synced from an organization's directory via Directory Sync.",
        "docs_url": "https://workos.com/docs/reference/directory-sync/directory-group",
        "columns": _columns(
            webhook_synced=True,
            directory_id="ID of the directory the group was synced from.",
            organization_id="ID of the organization the directory belongs to.",
            name="The group's name.",
        ),
    },
    "waitlist_entries": {
        "description": "An email address on an AuthKit waitlist, with its approval state.",
        "docs_url": "https://workos.com/docs/reference/authkit/waitlist",
        "columns": _columns(
            email="The email address of the user on the waitlist.",
            state="State of the entry: pending, approved, or denied.",
            approved_at="Time at which the entry was approved. Null if it is not approved.",
            additional_fields="Additional fields the user submitted when they joined the waitlist.",
            waitlist_id="ID of the waitlist the entry belongs to.",
        ),
    },
    "organization_memberships": {
        "description": "A user's membership in an organization, with the roles the user holds there.",
        "docs_url": "https://workos.com/docs/reference/authkit/organization-membership",
        "columns": _columns(
            user_id="ID of the user who holds the membership.",
            organization_id="ID of the organization the membership belongs to.",
            organization_name="Name of the organization the membership belongs to.",
            role="The user's primary role in the organization, as an object with a `slug`.",
            roles="All the roles the user holds in the organization, each with a `slug`.",
            status="Status of the membership: active, inactive, or pending.",
            directory_managed="Whether a Directory Sync connection manages the membership.",
            custom_attributes="Attributes from the linked directory user or SSO profile.",
        ),
    },
    "invitations": {
        "description": "An invitation for an email address to join an organization through AuthKit.",
        "docs_url": "https://workos.com/docs/reference/authkit/invitation",
        "columns": _columns(
            email="The email address of the recipient.",
            state="State of the invitation: pending, accepted, expired, or revoked.",
            accepted_at="Time at which the invitation was accepted. Null if it is not accepted.",
            revoked_at="Time at which the invitation was revoked. Null if it is not revoked.",
            expires_at="Time at which the invitation expires.",
            organization_id="ID of the organization that the recipient will join.",
            inviter_user_id="ID of the user who sent the invitation, if provided.",
            accepted_user_id="ID of the user who accepted the invitation, once accepted.",
            role_slug="Slug of the role the recipient gets on acceptance. Null when the invitation has no organization.",
        ),
    },
    "roles": {
        "description": "A role defined for the whole WorkOS environment, with the permissions it grants.",
        "docs_url": "https://workos.com/docs/reference/roles/role",
        "columns": _columns(
            name="A descriptive name for the role.",
            slug="A unique key for the role. Memberships and invitations refer to roles by this slug.",
            description="A description of the role.",
            permissions="The permission slugs assigned to the role.",
            type="The type of role. For environment roles, this is always EnvironmentRole.",
            resource_type_slug="The slug of the resource type the role is scoped to.",
        ),
    },
    "organization_groups": {
        "description": "A group of organization memberships inside one organization.",
        "docs_url": "https://workos.com/docs/reference/groups",
        "columns": _columns(
            organization_id="ID of the organization the group belongs to.",
            name="The name of the group.",
            description="A description of the group.",
        ),
    },
    "events": {
        "description": "An event that records activity in WorkOS or in a connected identity or directory provider.",
        "docs_url": "https://workos.com/docs/reference/events",
        "columns": {
            "id": "Unique identifier for the event.",
            "object": "String describing the object's WorkOS type. Always event.",
            "event": "The type of event that occurred, such as user.created or dsync.user.updated.",
            "data": "The event payload, in the shape of the WorkOS object that the event is about.",
            "created_at": "Time at which the event occurred.",
            "context": "Additional context about the event.",
        },
    },
}
