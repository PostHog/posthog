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
    # Teams the bearer token (personal API key or OAuth access token) is scoped to.
    # `team_id` itself is the user's `current_team_id` and can swap when the user
    # switches teams in the UI — that's unreliable for resolving the rate-limit
    # multiplier. `scoped_team_ids` is set on the token and stable for its lifetime,
    # so we use it as the authoritative source for multiplier resolution when set.
    # None / empty means unscoped (no constraint), and we fall back to `team_id`.
    scoped_team_ids: list[int] | None = None


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
