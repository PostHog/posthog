import time
import secrets

_TOKEN_TTL_SECONDS = 3600
_tokens: dict[str, tuple[str, float]] = {}


def issue_reset_token(email: str) -> str:
    token = secrets.token_urlsafe(32)
    _tokens[token] = (email, time.time() + _TOKEN_TTL_SECONDS)
    return token


def redeem_reset_token(token: str) -> str | None:
    entry = _tokens.pop(token, None)
    if entry is None:
        return None
    email, expires_at = entry
    if time.time() > expires_at:
        return None
    return email
