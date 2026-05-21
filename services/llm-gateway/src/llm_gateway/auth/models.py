from dataclasses import dataclass
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
    # The team's `posthog_team.api_token` — used by quota-limit throttles that
    # read Django's `@posthog/quota-limits/...` Redis sets, which are keyed by
    # team API token rather than team_id.
    team_api_token: str | None = None


def resolve_distinct_id(auth_user: AuthenticatedUser, end_user_id: str | None) -> str:
    # OAuth tokens identify the human; everything else prefers end_user_id so
    # events land on the customer-facing person profile.
    if auth_user.auth_method == "oauth_access_token":
        return auth_user.distinct_id
    return end_user_id or auth_user.distinct_id


def has_required_scope(scopes: list[str], required: str = "llm_gateway:read", *, allow_wildcard: bool = False) -> bool:
    if not scopes:
        return False
    if allow_wildcard and "*" in scopes:
        return True
    return required in scopes
