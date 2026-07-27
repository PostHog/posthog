"""Canonical, documentation-sourced descriptions for Clerk endpoints and columns.

Sourced from the official Clerk Backend API reference (https://clerk.com/docs/reference/backend-api).
Keyed by the endpoint names in `settings.py` `CLERK_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Clerk table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most Clerk objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "object": "String describing the object's Clerk type (e.g. 'user', 'organization').",
    "created_at": "Time at which the object was created, as a Unix timestamp in milliseconds.",
    "updated_at": "Time at which the object was last updated, as a Unix timestamp in milliseconds.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "users": {
        "description": "A user account in the Clerk instance, including identity and authentication details.",
        "docs_url": "https://clerk.com/docs/reference/backend-api/tag/Users",
        "columns": _columns(
            first_name="The user's first name.",
            last_name="The user's last name.",
            username="The user's unique username, if set.",
            email_addresses="List of email addresses associated with the user.",
            primary_email_address_id="ID of the user's primary email address.",
            phone_numbers="List of phone numbers associated with the user.",
            primary_phone_number_id="ID of the user's primary phone number.",
            image_url="URL of the user's profile image.",
            last_sign_in_at="Time the user last signed in, as a Unix timestamp in milliseconds.",
            banned="Whether the user is banned from signing in.",
            locked="Whether the user is temporarily locked out.",
            two_factor_enabled="Whether the user has two-factor authentication enabled.",
            mfa_disabled_at="Time at which the user disabled multi-factor authentication, as a Unix timestamp in milliseconds.",
            public_metadata="Metadata visible to the frontend and backend.",
            private_metadata="Metadata visible only to the backend.",
            unsafe_metadata="Metadata that can be read and updated from the frontend; treat as untrusted.",
            external_id="An external identifier you can attach to the user.",
        ),
    },
    "organizations": {
        "description": "An organization in the Clerk instance that groups users into a shared team.",
        "docs_url": "https://clerk.com/docs/reference/backend-api/tag/Organizations",
        "columns": _columns(
            name="The organization's name.",
            slug="The organization's URL-friendly unique slug.",
            image_url="URL of the organization's logo image.",
            members_count="Number of members in the organization.",
            max_allowed_memberships="Maximum number of members the organization can have.",
            created_by="ID of the user who created the organization.",
            public_metadata="Metadata visible to the frontend and backend.",
            private_metadata="Metadata visible only to the backend.",
        ),
    },
    "organization_memberships": {
        "description": "A membership linking a user to an organization, with their role in it.",
        "docs_url": "https://clerk.com/docs/reference/backend-api/tag/Organization-Memberships",
        "columns": _columns(
            organization="The organization the membership belongs to.",
            public_user_data="Public profile data of the member user.",
            role="The member's role within the organization (e.g. admin, basic_member).",
            permissions="List of permissions granted to the member.",
        ),
    },
    "invitations": {
        "description": "An invitation sent to an email address to join the Clerk instance.",
        "docs_url": "https://clerk.com/docs/reference/backend-api/tag/Invitations",
        "columns": _columns(
            email_address="Email address the invitation was sent to.",
            status="Status of the invitation (pending, accepted, revoked, or expired).",
            url="URL the invitee follows to accept the invitation.",
            revoked="Whether the invitation has been revoked.",
            public_metadata="Metadata visible to the frontend and backend.",
        ),
    },
}
