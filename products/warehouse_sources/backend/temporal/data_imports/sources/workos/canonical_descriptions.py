"""Canonical, documentation-sourced descriptions for WorkOS endpoints and columns.

Sourced from the official WorkOS API reference (https://workos.com/docs/reference). Keyed by the
endpoint names in `settings.py` `WORKOS_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced WorkOS table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most WorkOS objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "object": "String describing the object's WorkOS type.",
    "created_at": "Time at which the object was created.",
    "updated_at": "Time at which the object was last updated.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "organizations": {
        "description": "An organization (a tenant/company) in WorkOS that users and connections belong to.",
        "docs_url": "https://workos.com/docs/reference/organization",
        "columns": _columns(
            name="The organization's display name.",
            domains="Verified domains associated with the organization.",
            allow_profiles_outside_organization="Whether users outside the organization's domains may sign in.",
        ),
    },
    "users": {
        "description": "A user managed by WorkOS User Management (AuthKit).",
        "docs_url": "https://workos.com/docs/reference/user-management/user",
        "columns": _columns(
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
            directory_id="ID of the directory the group was synced from.",
            organization_id="ID of the organization the directory belongs to.",
            name="The group's name.",
        ),
    },
}
