from dataclasses import dataclass


@dataclass
class ClerkEndpointConfig:
    name: str
    path: str
    partition_key: str = "created_at"
    page_size: int = 100  # Clerk default, max is 500
    # Some Clerk endpoints return {data: [...], total_count: ...}, others return direct arrays
    is_wrapped_response: bool = False


# Note: Clerk API does not support filtering by updated_at, so only full refresh is supported.
CLERK_ENDPOINTS: dict[str, ClerkEndpointConfig] = {
    "users": ClerkEndpointConfig(name="users", path="/users"),
    "organizations": ClerkEndpointConfig(name="organizations", path="/organizations", is_wrapped_response=True),
    "organization_memberships": ClerkEndpointConfig(
        name="organization_memberships", path="/organization_memberships", is_wrapped_response=True
    ),
    "invitations": ClerkEndpointConfig(name="invitations", path="/invitations"),
}

ENDPOINTS = tuple(CLERK_ENDPOINTS.keys())
