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
    from slack_sdk.errors import SlackApiError

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


def get_cached_auth_state(integration_id: int) -> SlackIntegrationAuthState | None:
    """Return the cached verdict, or ``None`` on miss. Cheap.

    Django's cache backend pickles the dataclass directly; ``isinstance`` guards
    a value of an unexpected shape (e.g. a future schema migration that hasn't
    drained the cache) by treating it as a miss instead of crashing the resolver.
    """
    raw = cache.get(_cache_key(integration_id))
    return raw if isinstance(raw, SlackIntegrationAuthState) else None


def write_auth_state_ok(integration_id: int, bot_user_id: str | None) -> None:
    """Mark the install healthy. Called from the resolver's eager ``auth.test``
    on cache miss; not from per-mention call sites (``get_slack_email_for_user``
    et al), which leave positive verdicts to the resolver to keep the cache
    truthful about what the live token can actually do.
    """
    cache.set(
        _cache_key(integration_id),
        SlackIntegrationAuthState(ok=True, bot_user_id=bot_user_id, error_code=None, checked_at=timezone.now()),
        timeout=SLACK_AUTH_STATE_CACHE_TTL_SECONDS,
    )


def write_auth_state_broken(integration_id: int, error_code: str) -> None:
    """Mark the install broken. Callers should only invoke this for auth-class
    Slack error codes — see ``SLACK_AUTH_FAILURE_CODES``."""
    cache.set(
        _cache_key(integration_id),
        SlackIntegrationAuthState(ok=False, bot_user_id=None, error_code=error_code, checked_at=timezone.now()),
        timeout=SLACK_AUTH_STATE_CACHE_TTL_SECONDS,
    )
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


def classify_slack_api_error(exc: "SlackApiError") -> tuple[str | None, bool]:
    """Return ``(error_code, is_token_broken)``. Centralizes the
    ``exc.response.get("error") + membership check`` dance so every call site
    (resolver eager-check, ``get_slack_email_for_user``, ``get_cached_bot_user_id``)
    decides "drop this install from the candidate list" against the same rule.
    ``error_code`` is ``None`` when Slack didn't attach a recognizable error to
    the exception.
    """
    error_code = exc.response.get("error") if exc.response else None
    if not isinstance(error_code, str):
        return None, False
    return error_code, error_code in SLACK_AUTH_FAILURE_CODES


def _resolve_one_candidate_state(
    candidate: "Integration", slack_user_id: str | None
) -> SlackIntegrationAuthState | None:
    """Return the auth-state verdict for ``candidate``, populating the cache via
    ``auth.test`` on miss. Returns ``None`` when the verdict is unknown
    (transient failure, non-auth-class Slack error). The caller drops these
    candidates from the resulting list — see ``check_integrations_auth_and_filter``.
    """
    cached = get_cached_auth_state(candidate.id)
    if cached is not None:
        return cached

    # Inline-imported so the module's pure cache primitives stay importable
    # without pulling in the Slack SDK + ORM (facade re-export, test fixtures).
    from slack_sdk.errors import SlackApiError  # noqa: PLC0415

    from posthog.models.integration import SlackIntegration  # noqa: PLC0415

    try:
        response = SlackIntegration(candidate).client.auth_test()
    except SlackApiError as exc:
        error_code, token_broken = classify_slack_api_error(exc)
        if token_broken and error_code is not None:
            write_auth_state_broken(candidate.id, error_code)
            logger.warning(
                "slack_app_auth_test_token_broken",
                integration_id=candidate.id,
                slack_team_id=candidate.integration_id,
                slack_user_id=slack_user_id,
                error_code=error_code,
            )
            # Return the state we just wrote rather than re-reading from the
            # cache: under eviction or a concurrent invalidate the read-back
            # could come up None, which the caller would treat as "unknown"
            # and drop a candidate we just confirmed is broken (vs the
            # symmetric problem on the ok path of dropping a freshly-healthy
            # candidate). Constructing inline is also one less Redis hop.
            return SlackIntegrationAuthState(
                ok=False, bot_user_id=None, error_code=error_code, checked_at=timezone.now()
            )
        # Non-auth-class Slack error (``ratelimited``, ``internal_error``, etc):
        # don't pollute the cache. The candidate is treated as unknown — and
        # under the current ``drop unhealthy`` contract that means dropped
        # from this mention's candidate list. The next mention re-probes.
        logger.warning(
            "slack_app_auth_test_non_auth_error",
            integration_id=candidate.id,
            slack_team_id=candidate.integration_id,
            slack_user_id=slack_user_id,
            error_code=error_code,
        )
        return None
    except Exception:
        # Transient (network blip, Slack 5xx): refusing to brick the workspace
        # for the full TTL on a one-off failure is intentional. Same as the
        # non-auth Slack error path above — dropped this mention, retried next.
        logger.warning(
            "slack_app_auth_test_transient_failure",
            integration_id=candidate.id,
            slack_team_id=candidate.integration_id,
            slack_user_id=slack_user_id,
            exc_info=True,
        )
        return None

    bot_user_id = response.get("user_id")
    bot_user_id_value = bot_user_id if isinstance(bot_user_id, str) and bot_user_id else None
    write_auth_state_ok(candidate.id, bot_user_id_value)
    # See note on the write_auth_state_broken path above — return the just-
    # written state rather than re-reading from the cache.
    return SlackIntegrationAuthState(ok=True, bot_user_id=bot_user_id_value, error_code=None, checked_at=timezone.now())


def check_integrations_auth_and_filter(
    candidates: list["Integration"],
    *,
    slack_user_id: str | None = None,
) -> list["Integration"]:
    """Check each candidate's bot-token health and return only the healthy ones,
    sorted with the freshest verdict first.

    Single entry point for the resolver: for every candidate the function
    consults the cache, runs ``auth.test`` on miss (populating the cache with
    the result), then drops anything not cached as ``ok=true``.

    Why drop rather than demote: the resolver's precedence ladder
    (thread mapping > user default > workspace default > sole candidate >
    picker) only honors a target that's *in the candidate list*. Keeping a
    broken install in the list — even at the back — lets a stale thread
    mapping or user-default route every mention through a dead token. Dropping
    it lets the existing "kind drift" fallback in ``resolve_from_candidates``
    walk down to the next precedence level naturally.

    Buckets that get **dropped**:

    - **unknown** — cache miss survived eager populate because ``auth.test``
      transiently errored (Slack 5xx, network blip, ``ratelimited`` /
      ``internal_error`` from Slack). The cache is left untouched so the next
      mention retries, but we don't ship the user a probably-broken probe in
      the meantime.
    - **broken** — cached ``ok=false``. Recovery paths: the 6h TTL expires,
      the OAuth reconnect callback invalidates the entry, or a subsequent
      ``auth.test`` succeeds (the cache also expires naturally).

    **Known trade-off**: a Slack control-plane outage that makes ``auth.test``
    fail transiently for every install puts the workspace into the empty-result
    path for the duration of the outage — every Slack surface (mentions,
    link_shared/unfurl, member_joined_channel onboarding, cross-region routing
    probe) silently drops events even though the install's stored bot token
    may still work for other Slack endpoints (``chat.postMessage``,
    ``chat.unfurl``). The bet is that auth.test failures genuinely correlate
    with downstream-call failures more often than not, and that "silent drop
    during a Slack incident" is acceptable for the recovery simplicity it
    buys. If that bet stops holding, the fix is to expose a per-call-site
    ``require_healthy`` switch so link_shared / unfurl can opt out.

    Slack ``auth.test`` is Tier 4 (100+/min/workspace) so the per-mention cost
    is fine even for orgs with many installs on the same workspace. Concurrent
    mentions racing here just overwrite each other with the same verdict.

    Empty return when every candidate is broken/unknown is intentional and
    upstream code already handles it: ``_resolve_region_or_terminal_route``
    routes events to ``ROUTE_NO_INTEGRATION`` when no candidates are present,
    matching the behavior we'd see if the DB had no rows for this workspace.

    Every failure log includes ``slack_team_id`` (workspace), ``integration_id``
    (the broken install's PK) and ``slack_user_id`` of the mentioning user (when
    the caller has it). That's the minimum tuple support needs to pin a customer
    report to the exact install + token state without grepping through three
    files of upstream context.
    """
    if not candidates:
        return candidates

    healthy: list[tuple[Integration, datetime]] = []
    unknown: list[Integration] = []
    broken: list[Integration] = []
    for candidate in candidates:
        state = _resolve_one_candidate_state(candidate, slack_user_id)
        if state is None:
            unknown.append(candidate)
        elif state.ok:
            healthy.append((candidate, state.checked_at))
        else:
            broken.append(candidate)

    healthy.sort(key=lambda pair: pair[1], reverse=True)
    result = [c for c, _ in healthy]
    if broken or unknown:
        # ``candidates`` is workspace-homogeneous (the resolver's DB query
        # filters by ``integration_id=slack_team_id``), so reading the
        # workspace ID off any one row is safe. Escalate to ``warning`` only
        # when the filter left nothing AND we know at least one install is
        # actually broken — a Slack 5xx that wipes every candidate into the
        # ``unknown`` bucket would otherwise spam warning logs for every
        # workspace during a Slack incident.
        log = logger.warning if not result and broken else logger.info
        log(
            "slack_app_load_integrations_filtered",
            slack_team_id=candidates[0].integration_id,
            slack_user_id=slack_user_id,
            broken_integration_ids=[c.id for c in broken],
            unknown_integration_ids=[c.id for c in unknown],
            healthy_integration_ids=[c.id for c, _ in healthy],
        )
    return result
