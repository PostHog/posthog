"""Reset PostHog Code usage / rate-limit counters in the gateway Redis.

Two kinds of limit can be reset:

* cost     — the posthog_code per-user cost counters (burst + sustained), and
             optionally the product-wide aggregate cost pool (--product-total).
* request  — the per-user request-rate counters (burst + sustained). These are
             keyed by user id alone and are NOT product-scoped, so resetting
             them lifts the user's request-rate limit across every product.

By default both kinds are reset; pass --cost or --request to narrow. With no
--user-id every user is reset; pass one or more --user-id to scope it.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys

import structlog
from redis.asyncio import Redis

from llm_gateway.config import get_settings
from llm_gateway.services.plan_resolver import POSTHOG_CODE_PRODUCT

logger = structlog.get_logger(__name__)

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


def _non_empty_user_id(value: str) -> str:
    if not value:
        raise argparse.ArgumentTypeError("--user-id cannot be empty")
    return value


async def _amain(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="reset-posthog-code-usage",
        description=(
            "Reset PostHog Code usage / rate-limit counters in the gateway Redis. "
            "Resets every user unless --user-id is given, and both cost and request-rate "
            "counters unless --cost or --request is given."
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="Count keys without deleting.")
    parser.add_argument(
        "--user-id",
        action="append",
        dest="user_ids",
        type=_non_empty_user_id,
        help="Reset only this user's counters (the end_user_id in the cache key). Repeatable.",
    )
    parser.add_argument(
        "--cost",
        action="store_true",
        help="Reset only the posthog_code cost counters. Combine with --request for both; "
        "if neither is given, both are reset.",
    )
    parser.add_argument(
        "--request",
        action="store_true",
        help="Reset only the per-user request-rate counters. Combine with --cost for both; "
        "if neither is given, both are reset.",
    )
    parser.add_argument(
        "--product-total",
        action="store_true",
        help="Also reset the product-wide aggregate cost pool (affects all users).",
    )
    args = parser.parse_args(argv)

    # When neither type is named, reset both. --product-total is a cost-side
    # pool controlled by its own flag, independent of these.
    reset_cost = args.cost or not args.request
    reset_request = args.request or not args.cost

    settings = get_settings()
    if not settings.redis_url:
        logger.error("redis_url_not_configured")
        return 1

    redis: Redis = Redis.from_url(settings.redis_url)
    mode = "DRY RUN" if args.dry_run else "EXECUTED"
    total = 0

    # (label, user_id) for each user-scoped target. No --user-id means all users.
    targets: list[tuple[str, str | None]]
    if args.user_ids:
        targets = [(f"user {user_id}", user_id) for user_id in args.user_ids]
    else:
        targets = [("all users", None)]

    for label, user_id in targets:
        if reset_cost:
            deleted = await reset_keys(redis, cost_patterns(user_id), dry_run=args.dry_run)
            total += deleted
            print(f"[{mode}] {label} cost: {deleted} keys")
        if reset_request:
            deleted = await reset_keys(redis, request_patterns(user_id), dry_run=args.dry_run)
            total += deleted
            print(f"[{mode}] {label} request-rate: {deleted} keys")

    if args.product_total:
        deleted = await reset_keys(redis, product_patterns(), dry_run=args.dry_run)
        total += deleted
        print(f"[{mode}] product-wide cost pool: {deleted} keys")

    print(f"[{mode}] reset posthog_code limits: {total} keys total")
    return 0


def main() -> None:
    sys.exit(asyncio.run(_amain(sys.argv[1:])))


if __name__ == "__main__":
    main()
