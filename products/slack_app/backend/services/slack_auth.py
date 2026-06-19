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
from typing import TYPE_CHECKING

from django.core.cache import cache
from django.utils import timezone

import structlog

if TYPE_CHECKING:
    from posthog.models.integration import Integration

logger = structlog.get_logger(__name__)

# Six hours matches the precedent set by the previous bot-user-id cache —
# long enough to amortize the per-mention check, short enough that a stale
# negative verdict self-heals without manual intervention.
SLACK_AUTH_STATE_CACHE_TTL_SECONDS = 60 * 60 * 6

# Slack error codes that indicate the bot install can no longer authenticate.
# Shared across the auth-state writers so a single source decides what counts
# as "negative cache material" — transient/network failures must NOT brick the
# workspace by writing ``ok=false`` for the full TTL.
SLACK_AUTH_FAILURE_CODES = frozenset(
    {"token_revoked", "invalid_auth", "not_authed", "account_inactive", "token_expired"}
)


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


def check_integrations_auth_and_filter(
    candidates: list["Integration"],
    *,
    slack_user_id: str | None = None,
) -> list["Integration"]:
    """Check each candidate's bot-token health and return them reordered so a
    healthy install lands at index 0.

    Single entry point for the resolver: for every candidate the function
    consults the cache, runs ``auth.test`` on miss (populating the cache with
    the result), and then ranks the list:

    - **healthy** (cached ``ok=true``) — sorted by ``checked_at`` DESC so a
      freshly-reconnected install lands ahead of one that's been healthy for
      hours.
    - **unknown** (cache miss survived eager populate because ``auth.test``
      transiently errored — Slack 5xx, network blip) — kept in the middle.
    - **broken** (cached ``ok=false``) — demoted to the end, **never dropped**.
      Refusing to strand the workspace on stale negative cache: if every
      candidate is broken, the resolver still tries them and the success-path
      hook in ``get_slack_email_for_user`` flips the cache back to healthy.

    Slack ``auth.test`` is Tier 4 (100+/min/workspace) so the per-mention cost
    is fine even for orgs with many installs on the same workspace. Concurrent
    mentions racing here just overwrite each other with the same verdict.

    Every failure log includes ``slack_team_id`` (workspace), ``integration_id``
    (the broken install's PK) and ``slack_user_id`` of the mentioning user (when
    the caller has it). That's the minimum tuple support needs to pin a customer
    report to the exact install + token state without grepping through three
    files of upstream context.
    """
    # Inline-imported so this module stays cheap for callers that only need
    # the cache primitives (the facade re-export, test fixtures). The Slack
    # SDK + Integration ORM are the heavy part.
    from slack_sdk.errors import SlackApiError  # noqa: PLC0415

    from posthog.models.integration import SlackIntegration  # noqa: PLC0415

    if not candidates:
        return candidates

    for candidate in candidates:
        if get_cached_auth_state(candidate.id) is not None:
            continue
        try:
            response = SlackIntegration(candidate).client.auth_test()
        except SlackApiError as exc:
            error_code = exc.response.get("error") if exc.response else None
            if isinstance(error_code, str) and error_code in SLACK_AUTH_FAILURE_CODES:
                write_auth_state_broken(candidate.id, error_code)
                logger.warning(
                    "slack_app_auth_test_token_broken",
                    integration_id=candidate.id,
                    slack_team_id=candidate.integration_id,
                    slack_user_id=slack_user_id,
                    error_code=error_code,
                )
            else:
                # Non-auth-class Slack errors say nothing about token validity;
                # leave the cache untouched so the next call can repopulate.
                logger.warning(
                    "slack_app_auth_test_non_auth_error",
                    integration_id=candidate.id,
                    slack_team_id=candidate.integration_id,
                    slack_user_id=slack_user_id,
                    error_code=error_code,
                )
            continue
        except Exception:
            # Transient network / Slack 5xx — refusing to brick the workspace
            # for the full TTL on a one-off failure is intentional.
            logger.warning(
                "slack_app_auth_test_transient_failure",
                integration_id=candidate.id,
                slack_team_id=candidate.integration_id,
                slack_user_id=slack_user_id,
                exc_info=True,
            )
            continue
        bot_user_id = response.get("user_id")
        write_auth_state_ok(
            candidate.id,
            bot_user_id if isinstance(bot_user_id, str) and bot_user_id else None,
        )

    healthy: list[tuple[Integration, datetime]] = []
    unknown: list[Integration] = []
    broken: list[Integration] = []
    for candidate in candidates:
        state = get_cached_auth_state(candidate.id)
        if state is None:
            unknown.append(candidate)
        elif state.ok:
            healthy.append((candidate, state.checked_at))
        else:
            broken.append(candidate)

    healthy.sort(key=lambda pair: pair[1], reverse=True)
    reordered = [c for c, _ in healthy] + unknown + broken
    if broken:
        # ``candidates`` is workspace-homogeneous (the resolver's DB query
        # filters by ``integration_id=slack_team_id``), so reading the
        # workspace ID off any one row is safe.
        logger.info(
            "slack_app_load_integrations_filtered",
            slack_team_id=candidates[0].integration_id,
            slack_user_id=slack_user_id,
            broken_integration_ids=[c.id for c in broken],
            healthy_integration_ids=[c.id for c, _ in healthy],
            unknown_integration_ids=[c.id for c in unknown],
        )
    return reordered
