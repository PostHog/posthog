from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class AuthenticatedUser:
    user_id: int
    team_id: int | None
    auth_method: str
    distinct_id: str
    scopes: list[str] | None = None
    token_expires_at: datetime | None = None
    application_id: str | None = None
    # All team ids the user is allowed to bill against — derived from their
    # organization memberships, intersected with the API key / OAuth token's
    # `scoped_teams` when set. Used to validate the client-provided
    # `X-PostHog-Team-Id` header.
    team_ids: frozenset[int] = field(default_factory=frozenset)


def has_required_scope(scopes: list[str], required: str = "llm_gateway:read", *, allow_wildcard: bool = False) -> bool:
    if not scopes:
        return False
    if allow_wildcard and "*" in scopes:
        return True
    return required in scopes
