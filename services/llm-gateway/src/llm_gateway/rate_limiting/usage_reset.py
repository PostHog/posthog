"""Shared helpers for inspecting and resetting PostHog Code usage / rate-limit
counters in the gateway Redis.

Two kinds of limit live here:

* cost     — the posthog_code per-user cost counters (burst + sustained), and
             the product-wide aggregate cost pool. This is the live, per-user,
             per-product limit the gateway actually enforces.
* request  — the per-user request-rate counters (burst + sustained). These are
             keyed by user id alone and are NOT product-scoped. They are
             currently dormant (no live throttle writes them), kept here as a
             safety net for if the request-rate limiter is re-enabled.

The CLI (`cli/reset_posthog_code_usage.py`) and the staff admin endpoint
(`api/admin.py`) both build on these helpers so the key shapes stay in one
place.
"""

from __future__ import annotations

import re

from redis.asyncio import Redis

from llm_gateway.config import DEFAULT_USER_COST_LIMIT, get_settings
from llm_gateway.services.plan_resolver import POSTHOG_CODE_PRODUCT

# The two per-user cost throttle scopes (_UserCostThrottleBase subclasses).
COST_SCOPES = ("user_cost_burst", "user_cost_sustained")
# The two per-user request-rate scopes (RateLimiter).
REQUEST_SCOPES = ("burst", "sustained")

SCAN_COUNT = 500
UNLINK_BATCH = 500

_REDIS_GLOB_METACHARS = re.compile(r"([\\*?\[\]])")


def _escape(user_id: str) -> str:
    # Escape glob metachars so a user_id like "10*" cannot expand the SCAN match
    # and delete unrelated users' counters.
    return _REDIS_GLOB_METACHARS.sub(r"\\\1", user_id)


# Mirrors the cache key built by _UserCostThrottleBase._get_cache_key in
# rate_limiting/cost_throttles.py (plus the outer "ratelimit:" added by
# redis_limiter and the ":tm{n}" / ":period:{n}" suffixes). Update both ends if
# the key shape changes.
def cost_patterns(user_id: str | None) -> tuple[str, ...]:
    if user_id is None:
        return tuple(f"ratelimit:cost:user:{scope}:{POSTHOG_CODE_PRODUCT}:*" for scope in COST_SCOPES)
    safe_id = _escape(user_id)
    patterns: list[str] = []
    for scope in COST_SCOPES:
        base = f"ratelimit:cost:user:{scope}:{POSTHOG_CODE_PRODUCT}:{safe_id}"
        # Bare base key, plus its colon-suffixed variants. The trailing ":"
        # stops user "100" from also matching user "1000".
        patterns.append(base)
        patterns.append(f"{base}:*")
    return tuple(patterns)


# Mirrors RateLimiter.check: "ratelimit:{scope}:{user_id}". Exact keys, no
# suffixes — a single-user reset matches the escaped key exactly.
def request_patterns(user_id: str | None) -> tuple[str, ...]:
    if user_id is None:
        return tuple(f"ratelimit:{scope}:*" for scope in REQUEST_SCOPES)
    safe_id = _escape(user_id)
    return tuple(f"ratelimit:{scope}:{safe_id}" for scope in REQUEST_SCOPES)


def product_patterns() -> tuple[str, ...]:
    base = f"ratelimit:cost:product:{POSTHOG_CODE_PRODUCT}"
    return (base, f"{base}:tm*")


async def reset_keys(redis: Redis, patterns: tuple[str, ...], *, dry_run: bool) -> int:
    """SCAN each pattern and UNLINK the matches in batches. Returns keys affected."""
    affected = 0
    for pattern in patterns:
        batch: list[str] = []
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=SCAN_COUNT)
            for k in keys:
                batch.append(k.decode() if isinstance(k, bytes) else k)
                if len(batch) >= UNLINK_BATCH:
                    affected += await _flush(redis, batch, dry_run=dry_run)
            if cursor == 0:
                break
        if batch:
            affected += await _flush(redis, batch, dry_run=dry_run)
    return affected


async def _flush(redis: Redis, batch: list[str], *, dry_run: bool) -> int:
    n = len(batch)
    if not dry_run:
        await redis.unlink(*batch)
    batch.clear()
    return n


def _base_limit_for(scope: str) -> float:
    """The configured base posthog_code limit for a cost scope, before team
    multipliers and free-plan adjustments (which depend on per-request context
    we don't have here). Useful as a reference value in the read-only view."""
    config = get_settings().user_cost_limits.get(POSTHOG_CODE_PRODUCT, DEFAULT_USER_COST_LIMIT)
    if scope == "user_cost_burst":
        return config.burst_limit_usd
    if scope == "user_cost_sustained":
        return config.sustained_limit_usd
    return 0.0


class CostKeyUsage:
    """A single live cost counter for a user: how much has accumulated and when
    it resets. Read-only snapshot for the admin view."""

    def __init__(self, key: str, scope: str, used_usd: float, resets_in_seconds: int, base_limit_usd: float) -> None:
        self.key = key
        self.scope = scope
        self.used_usd = used_usd
        self.resets_in_seconds = resets_in_seconds
        self.base_limit_usd = base_limit_usd

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "scope": self.scope,
            "used_usd": self.used_usd,
            "resets_in_seconds": self.resets_in_seconds,
            "base_limit_usd": self.base_limit_usd,
        }


def _scope_from_cost_key(key: str) -> str | None:
    # ratelimit:cost:user:{scope}:{product}:{user_id}[:tm{n}][:period:{n}]
    parts = key.split(":")
    if len(parts) < 6 or parts[0] != "ratelimit" or parts[1] != "cost" or parts[2] != "user":
        return None
    return parts[3]


async def scan_cost_usage(redis: Redis, user_id: str) -> list[CostKeyUsage]:
    """Return the user's live posthog_code cost counters with current value and TTL.

    Reads raw counter values rather than resolving the user's plan/team, so it
    avoids a per-product billing roundtrip. The reported limit is the configured
    base limit (team multipliers / free-plan rules are not applied), so treat
    `base_limit_usd` as a reference, not the exact enforced ceiling.
    """
    results: list[CostKeyUsage] = []
    seen: set[str] = set()
    for pattern in cost_patterns(user_id):
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=SCAN_COUNT)
            for raw in keys:
                key = raw.decode() if isinstance(raw, bytes) else raw
                if key in seen:
                    continue
                seen.add(key)
                scope = _scope_from_cost_key(key)
                if scope is None:
                    continue
                raw_value = await redis.get(key)
                ttl = await redis.ttl(key)
                results.append(
                    CostKeyUsage(
                        key=key,
                        scope=scope,
                        used_usd=_parse_float(raw_value),
                        resets_in_seconds=max(0, ttl),
                        base_limit_usd=_base_limit_for(scope),
                    )
                )
            if cursor == 0:
                break
    results.sort(key=lambda u: u.key)
    return results


def _parse_float(raw: object) -> float:
    if raw is None:
        return 0.0
    try:
        return float(raw.decode() if isinstance(raw, bytes) else raw)
    except (ValueError, TypeError):
        return 0.0
