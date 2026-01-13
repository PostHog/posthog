from dataclasses import dataclass
from datetime import datetime


@dataclass
class AuthenticatedUser:
    user_id: int
    team_id: int | None
    auth_method: str
    scopes: list[str] | None = None
    token_expires_at: datetime | None = None
    application_id: str | None = None


def has_required_scope(scopes: list[str], required: str = "llm_gateway:read") -> bool:
    if not scopes:
        return False
    return "*" in scopes or required in scopes
