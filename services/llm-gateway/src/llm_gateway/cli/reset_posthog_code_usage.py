"""Reset PostHog Code usage counters in Redis. Resets all users by default, or a single user with --user-id."""

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

SCOPES = ("user_cost_burst", "user_cost_sustained")

SCAN_COUNT = 500
UNLINK_BATCH = 500

_REDIS_GLOB_METACHARS = re.compile(r"([\\*?\[\]])")


# Mirrors the cache key built by _UserCostThrottleBase._get_cache_key in
# rate_limiting/cost_throttles.py (with the outer "ratelimit:" added by
# redis_limiter). Update both ends if the key shape changes.
def _patterns_for(user_id: str | None) -> tuple[str, ...]:
    if user_id is None:
        return tuple(f"ratelimit:cost:user:{scope}:{POSTHOG_CODE_PRODUCT}:*" for scope in SCOPES)
    # Escape glob metachars so a user_id like "10*" cannot expand the SCAN
    # match and delete unrelated users' counters.
    safe_id = _REDIS_GLOB_METACHARS.sub(r"\\\1", user_id)
    # Two patterns per scope: the bare base key, plus its colon-suffixed
    # variants. The trailing ':' prevents user "100" from matching user "1000".
    patterns: list[str] = []
    for scope in SCOPES:
        base = f"ratelimit:cost:user:{scope}:{POSTHOG_CODE_PRODUCT}:{safe_id}"
        patterns.append(base)
        patterns.append(f"{base}:*")
    return tuple(patterns)


async def reset_usage(redis: Redis, *, dry_run: bool, user_id: str | None = None) -> int:
    deleted = 0
    for pattern in _patterns_for(user_id):
        batch: list[str] = []
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=SCAN_COUNT)
            for k in keys:
                batch.append(k.decode() if isinstance(k, bytes) else k)
                if len(batch) >= UNLINK_BATCH:
                    deleted += await _flush(redis, batch, dry_run=dry_run)
            if cursor == 0:
                break
        if batch:
            deleted += await _flush(redis, batch, dry_run=dry_run)
    return deleted


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
        description="Reset PostHog Code usage counters in the LLM gateway Redis. Resets every user unless --user-id is given.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Count keys without deleting.")
    parser.add_argument(
        "--user-id",
        type=_non_empty_user_id,
        help="Reset only the given user's counters (matches the end_user_id used in the cache key).",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.redis_url:
        logger.error("redis_url_not_configured")
        return 1

    redis: Redis = Redis.from_url(settings.redis_url)
    deleted = await reset_usage(redis, dry_run=args.dry_run, user_id=args.user_id)

    mode = "DRY RUN" if args.dry_run else "EXECUTED"
    scope = f"user {args.user_id}" if args.user_id is not None else "all users"
    print(f"[{mode}] reset posthog_code usage ({scope}): {deleted} keys")
    return 0


def main() -> None:
    sys.exit(asyncio.run(_amain(sys.argv[1:])))


if __name__ == "__main__":
    main()
