"""One-shot cache-backed link codes, shared by chat providers without user OAuth.

Telegram and WhatsApp have no OAuth dance for end users: the "callback" is the bot
receiving a message that carries a code we minted for a logged-in PostHog user. The
code is a short random handle whose context (who minted it, for which team, for which
purpose) lives server-side in the cache — deep-link payloads (Telegram's 64-char
``/start`` limit, ``wa.me`` prefilled text) are too constrained for signed tokens.
"""

import secrets
from dataclasses import asdict, dataclass
from typing import Literal

from django.core.cache import cache

LINK_CODE_TTL_SECONDS = 15 * 60

LinkPurpose = Literal["link", "connect"]


@dataclass(frozen=True)
class ChatLinkCode:
    purpose: LinkPurpose
    posthog_user_id: int
    team_id: int


def _cache_key(provider: str, code: str) -> str:
    return f"{provider}_app:link_code:{code}"


def mint_link_code(*, provider: str, purpose: LinkPurpose, posthog_user_id: int, team_id: int) -> str:
    # 24 random bytes → 32 chars of [A-Za-z0-9_-], comfortably inside Telegram's
    # 64-char /start payload limit (the tightest carrier among providers).
    code = secrets.token_urlsafe(24)
    cache.set(
        _cache_key(provider, code),
        asdict(ChatLinkCode(purpose=purpose, posthog_user_id=posthog_user_id, team_id=team_id)),
        LINK_CODE_TTL_SECONDS,
    )
    return code


def redeem_link_code(provider: str, code: str, *, expected_purpose: LinkPurpose) -> ChatLinkCode | None:
    """One-shot: the code is deleted on first read regardless of purpose match."""
    if not code:
        return None
    key = _cache_key(provider, code)
    payload = cache.get(key)
    if payload is None:
        return None
    cache.delete(key)
    if not isinstance(payload, dict) or payload.get("purpose") != expected_purpose:
        return None
    try:
        return ChatLinkCode(
            purpose=payload["purpose"],
            posthog_user_id=int(payload["posthog_user_id"]),
            team_id=int(payload["team_id"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
