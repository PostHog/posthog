from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True, kw_only=True)
class ClerkFanOut:
    """A Clerk list endpoint that only answers when filtered by a parent object's id.

    `/sessions` needs `user_id` (or `client_id`) and `/m2m_tokens` needs `subject`; unfiltered
    calls are rejected. The filter travels as a query param, and the framework only substitutes
    resolved params into the path, so the child path carries the placeholder in its query string.
    """

    parent: str  # key in CLERK_ENDPOINTS whose rows drive the fan-out
    parent_field: str  # field on each parent row supplying the filter value
    query_param: str  # query param the child endpoint filters on


@dataclass
class ClerkEndpointConfig:
    name: str
    path: str
    # `None` for endpoints whose objects carry no creation timestamp, so there is nothing stable
    # to partition on (Clerk's `/domains` and `/billing/plans`).
    partition_key: Optional[str] = "created_at"
    page_size: int = 100  # Clerk default, max is 500
    # Some Clerk endpoints return {data: [...], total_count: ...}, others return direct arrays
    is_wrapped_response: bool = False
    # Key holding the row array in a wrapped response — `/m2m_tokens` uses `m2m_tokens`, not `data`.
    data_key: str = "data"
    fan_out: Optional[ClerkFanOut] = None
    # Names a Clerk feature that instances have to switch on. Clerk answers 402, or 400/403 with a
    # `*_not_enabled` code, for every account that hasn't. No retry or credential change fixes
    # that, so the table syncs zero rows and logs this name instead of failing the whole schema.
    gated_feature: Optional[str] = None


# Note: Clerk API does not support filtering by updated_at, so only full refresh is supported.
CLERK_ENDPOINTS: dict[str, ClerkEndpointConfig] = {
    "users": ClerkEndpointConfig(name="users", path="/users"),
    "organizations": ClerkEndpointConfig(name="organizations", path="/organizations", is_wrapped_response=True),
    "organization_memberships": ClerkEndpointConfig(
        name="organization_memberships", path="/organization_memberships", is_wrapped_response=True
    ),
    "invitations": ClerkEndpointConfig(name="invitations", path="/invitations"),
    "sessions": ClerkEndpointConfig(
        name="sessions",
        path="/sessions",
        fan_out=ClerkFanOut(parent="users", parent_field="id", query_param="user_id"),
    ),
    "organization_invitations": ClerkEndpointConfig(
        name="organization_invitations",
        path="/organization_invitations",
        is_wrapped_response=True,
        # Clerk answers 404 resource_not_found for the organization invitations list on instances
        # that don't have Organizations switched on — the same feature-off signal the domains and
        # OAuth applications endpoints give. Skip zero rows instead of failing the schema every run.
        gated_feature="Organizations",
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
    "allowlist_identifiers": ClerkEndpointConfig(
        name="allowlist_identifiers",
        path="/allowlist_identifiers",
        gated_feature="Restrictions (the allow-list and block-list)",
    ),
    "blocklist_identifiers": ClerkEndpointConfig(
        name="blocklist_identifiers",
        path="/blocklist_identifiers",
        is_wrapped_response=True,
        gated_feature="Restrictions (the allow-list and block-list)",
    ),
    "domains": ClerkEndpointConfig(
        name="domains",
        path="/domains",
        partition_key=None,
        is_wrapped_response=True,
        # Clerk answers 404 resource_not_found for the domains list on instances that don't have the
        # feature switched on — the same feature-off signal the OAuth applications and Restrictions
        # endpoints give. Skip zero rows instead of failing the schema every run.
        gated_feature="Satellite domains",
    ),
    "saml_connections": ClerkEndpointConfig(
        name="saml_connections", path="/saml_connections", is_wrapped_response=True
    ),
    "enterprise_connections": ClerkEndpointConfig(
        name="enterprise_connections", path="/enterprise_connections", is_wrapped_response=True
    ),
    "oauth_applications": ClerkEndpointConfig(
        name="oauth_applications",
        path="/oauth_applications",
        is_wrapped_response=True,
        # Clerk answers 404 resource_not_found for the OAuth applications list on instances that
        # haven't switched the feature on — the same feature-off signal the Restrictions endpoints
        # give. Skip zero rows instead of failing the schema every run.
        gated_feature="OAuth applications",
    ),
    "machines": ClerkEndpointConfig(name="machines", path="/machines", is_wrapped_response=True),
    # /api_keys and /m2m_tokens cap `limit` at 100 rather than 500.
    "api_keys": ClerkEndpointConfig(name="api_keys", path="/api_keys", is_wrapped_response=True),
    "m2m_tokens": ClerkEndpointConfig(
        name="m2m_tokens",
        path="/m2m_tokens",
        is_wrapped_response=True,
        data_key="m2m_tokens",
        fan_out=ClerkFanOut(parent="machines", parent_field="id", query_param="subject"),
    ),
    "redirect_urls": ClerkEndpointConfig(name="redirect_urls", path="/redirect_urls"),
    "jwt_templates": ClerkEndpointConfig(name="jwt_templates", path="/jwt_templates"),
    "email_templates": ClerkEndpointConfig(name="email_templates", path="/templates/email"),
    "sms_templates": ClerkEndpointConfig(name="sms_templates", path="/templates/sms"),
    "commerce_plans": ClerkEndpointConfig(
        name="commerce_plans",
        # Clerk renamed this from /commerce/plans to /billing/plans; the old path now answers 400.
        path="/billing/plans",
        partition_key=None,
        is_wrapped_response=True,
        gated_feature="Billing",
    ),
    "commerce_subscription_items": ClerkEndpointConfig(
        name="commerce_subscription_items",
        path="/billing/subscription_items",
        is_wrapped_response=True,
        gated_feature="Billing",
    ),
}

# Tables whose Clerk endpoint no longer exists. Dropping the name from CLERK_ENDPOINTS is what
# retires the table: schema discovery stops listing it, which disables syncing and leaves any
# already-imported rows in place. The reason lives here so a job that starts before the next
# discovery run explains itself rather than raising a KeyError.
RETIRED_ENDPOINTS: dict[str, str] = {
    # https://clerk.com/docs/reference/backend-api — GET /v1/clients is marked deprecated and now
    # answers 410. Clerk offers no replacement listing endpoint.
    "clients": (
        "Clerk removed the clients endpoint from its API, so the clients table can't sync any more. "
        "Turn off syncing for this table."
    ),
}

ENDPOINTS = tuple(CLERK_ENDPOINTS.keys())
