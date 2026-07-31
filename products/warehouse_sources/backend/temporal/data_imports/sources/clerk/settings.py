from dataclasses import dataclass
from typing import Optional


@dataclass
class ClerkEndpointConfig:
    name: str
    path: str
    # `None` for endpoints whose objects carry no creation timestamp, so there is nothing stable
    # to partition on (Clerk's `/domains` and `/commerce/plans`).
    partition_key: Optional[str] = "created_at"
    page_size: int = 100  # Clerk default, max is 500
    # Some Clerk endpoints return {data: [...], total_count: ...}, others return direct arrays
    is_wrapped_response: bool = False
    # Key holding the row array in a wrapped response — `/m2m_tokens` uses `m2m_tokens`, not `data`.
    data_key: str = "data"


# Note: Clerk API does not support filtering by updated_at, so only full refresh is supported.
CLERK_ENDPOINTS: dict[str, ClerkEndpointConfig] = {
    "users": ClerkEndpointConfig(name="users", path="/users"),
    "organizations": ClerkEndpointConfig(name="organizations", path="/organizations", is_wrapped_response=True),
    "organization_memberships": ClerkEndpointConfig(
        name="organization_memberships", path="/organization_memberships", is_wrapped_response=True
    ),
    "invitations": ClerkEndpointConfig(name="invitations", path="/invitations"),
    "sessions": ClerkEndpointConfig(name="sessions", path="/sessions"),
    "clients": ClerkEndpointConfig(name="clients", path="/clients"),
    "organization_invitations": ClerkEndpointConfig(
        name="organization_invitations", path="/organization_invitations", is_wrapped_response=True
    ),
    "organization_domains": ClerkEndpointConfig(
        name="organization_domains", path="/organization_domains", is_wrapped_response=True
    ),
    "organization_roles": ClerkEndpointConfig(
        name="organization_roles", path="/organization_roles", is_wrapped_response=True
    ),
    "organization_permissions": ClerkEndpointConfig(
        name="organization_permissions", path="/organization_permissions", is_wrapped_response=True
    ),
    "role_sets": ClerkEndpointConfig(name="role_sets", path="/role_sets", is_wrapped_response=True),
    "waitlist_entries": ClerkEndpointConfig(
        name="waitlist_entries", path="/waitlist_entries", is_wrapped_response=True
    ),
    "allowlist_identifiers": ClerkEndpointConfig(name="allowlist_identifiers", path="/allowlist_identifiers"),
    "blocklist_identifiers": ClerkEndpointConfig(
        name="blocklist_identifiers", path="/blocklist_identifiers", is_wrapped_response=True
    ),
    "domains": ClerkEndpointConfig(name="domains", path="/domains", partition_key=None, is_wrapped_response=True),
    "saml_connections": ClerkEndpointConfig(
        name="saml_connections", path="/saml_connections", is_wrapped_response=True
    ),
    "enterprise_connections": ClerkEndpointConfig(
        name="enterprise_connections", path="/enterprise_connections", is_wrapped_response=True
    ),
    "oauth_applications": ClerkEndpointConfig(
        name="oauth_applications", path="/oauth_applications", is_wrapped_response=True
    ),
    "machines": ClerkEndpointConfig(name="machines", path="/machines", is_wrapped_response=True),
    # /api_keys and /m2m_tokens cap `limit` at 100 rather than 500.
    "api_keys": ClerkEndpointConfig(name="api_keys", path="/api_keys", is_wrapped_response=True),
    "m2m_tokens": ClerkEndpointConfig(
        name="m2m_tokens", path="/m2m_tokens", is_wrapped_response=True, data_key="m2m_tokens"
    ),
    "redirect_urls": ClerkEndpointConfig(name="redirect_urls", path="/redirect_urls"),
    "jwt_templates": ClerkEndpointConfig(name="jwt_templates", path="/jwt_templates"),
    "email_templates": ClerkEndpointConfig(name="email_templates", path="/templates/email"),
    "sms_templates": ClerkEndpointConfig(name="sms_templates", path="/templates/sms"),
    "commerce_plans": ClerkEndpointConfig(
        name="commerce_plans", path="/commerce/plans", partition_key=None, is_wrapped_response=True
    ),
    "commerce_subscription_items": ClerkEndpointConfig(
        name="commerce_subscription_items", path="/commerce/subscription_items", is_wrapped_response=True
    ),
}

ENDPOINTS = tuple(CLERK_ENDPOINTS.keys())
