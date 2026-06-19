"""Per-integration Slack auth-state cache.

Real Slack call outcomes (``users.info``, ``chat.postMessage``, ``auth.test``)
feed a small Redis-backed verdict that the resolver consults before picking a
probe. The goal is to skip integrations whose bot token has gone bad — a dead
install at ``candidates[0]`` (oldest by PK) silently broke every mention for
the workspace because nothing fell through to a healthier install.

Cache lifecycle:

- **Read**: cheap, never blocks. A miss means "we don't know yet" — the next
  real call will populate the entry.
- **Write on success**: every Slack call that proves the token works refreshes
  ``ok=true``. Opportunistic — we don't run defensive ``auth.test`` calls.
- **Write on auth-class error**: only the codes in
  ``products.slack_app.backend.api._SLACK_AUTH_FAILURE_CODES`` (token_revoked,
  invalid_auth, not_authed, account_inactive, token_expired) flip the cache to
  ``ok=false``. Transient failures (network, Slack 5xx, rate limits) leave the
  cache untouched — otherwise a Slack outage would brick every workspace for
  the full TTL.
- **Invalidate**: the OAuth reconnect callback hits the facade re-export at
  ``products.slack_app.backend.facade.api.invalidate_slack_integration_auth_state``
  to drop the cache key so the next call mints a fresh verdict.
"""

from dataclasses import dataclass
from datetime import datetime

from django.core.cache import cache
from django.utils import timezone

import structlog

logger = structlog.get_logger(__name__)

# Six hours matches the precedent set by ``SLACK_BOT_USER_ID_CACHE_TTL_SECONDS``
# in slack_user_info — long enough to amortize the per-mention check, short
# enough that a stale negative verdict self-heals without manual intervention.
SLACK_AUTH_STATE_CACHE_TTL_SECONDS = 60 * 60 * 6


@dataclass(frozen=True)
class SlackIntegrationAuthState:
    ok: bool
    bot_user_id: str | None
    error_code: str | None
    checked_at: datetime


def _cache_key(integration_id: int) -> str:
    return f"slack_app:auth_state:v1:{integration_id}"


def _deserialize(raw: object) -> SlackIntegrationAuthState | None:
    """Tolerate cache entries written by older code versions — drop them rather
    than blow up the resolver if the shape ever drifts."""
    if not isinstance(raw, dict):
        return None
    try:
        return SlackIntegrationAuthState(
            ok=bool(raw["ok"]),
            bot_user_id=raw["bot_user_id"],
            error_code=raw["error_code"],
            checked_at=raw["checked_at"],
        )
    except (KeyError, TypeError, ValueError):
        return None


def _serialize(state: SlackIntegrationAuthState) -> dict[str, object]:
    return {
        "ok": state.ok,
        "bot_user_id": state.bot_user_id,
        "error_code": state.error_code,
        "checked_at": state.checked_at,
    }


def get_cached_auth_state(integration_id: int) -> SlackIntegrationAuthState | None:
    """Return the cached verdict, or ``None`` on miss / malformed entry. Cheap."""
    return _deserialize(cache.get(_cache_key(integration_id)))


def write_auth_state_ok(integration_id: int, bot_user_id: str | None) -> None:
    """Mark the install healthy. Called from every successful Slack call that
    has proof the token works — both opportunistic refreshes (e.g. a successful
    ``users.info``) and explicit checks (``auth.test``).
    """
    state = SlackIntegrationAuthState(
        ok=True,
        bot_user_id=bot_user_id,
        error_code=None,
        checked_at=timezone.now(),
    )
    cache.set(_cache_key(integration_id), _serialize(state), timeout=SLACK_AUTH_STATE_CACHE_TTL_SECONDS)


def write_auth_state_broken(integration_id: int, error_code: str) -> None:
    """Mark the install broken. Callers should only invoke this for
    **auth-class** Slack error codes — see the module docstring."""
    state = SlackIntegrationAuthState(
        ok=False,
        bot_user_id=None,
        error_code=error_code,
        checked_at=timezone.now(),
    )
    cache.set(_cache_key(integration_id), _serialize(state), timeout=SLACK_AUTH_STATE_CACHE_TTL_SECONDS)
    logger.warning(
        "slack_app_auth_state_marked_broken",
        integration_id=integration_id,
        error_code=error_code,
    )


def invalidate_auth_state(integration_id: int) -> None:
    """Drop the cache entry so the next call mints a fresh verdict. Called by
    the OAuth reconnect callback via
    ``products.slack_app.backend.facade.api.invalidate_slack_integration_auth_state``."""
    cache.delete(_cache_key(integration_id))
    logger.info("slack_app_auth_state_invalidated", integration_id=integration_id)
