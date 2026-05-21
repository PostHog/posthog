"""Reset PostHog Code usage counters for every user in Redis."""

from __future__ import annotations

import argparse
import asyncio
import sys

import structlog
from redis.asyncio import Redis

from llm_gateway.config import get_settings
from llm_gateway.services.plan_resolver import POSTHOG_CODE_PRODUCT

logger = structlog.get_logger(__name__)

# Mirrors the cache key built by _UserCostThrottleBase._get_cache_key in
# rate_limiting/cost_throttles.py (with the outer "ratelimit:" added by
# redis_limiter). Update both ends if the key shape changes.
PATTERNS = (
    f"ratelimit:cost:user:user_cost_burst:{POSTHOG_CODE_PRODUCT}:*",
    f"ratelimit:cost:user:user_cost_sustained:{POSTHOG_CODE_PRODUCT}:*",
)

SCAN_COUNT = 500
UNLINK_BATCH = 500


async def reset_usage(redis: Redis, *, dry_run: bool) -> int:
    deleted = 0
    for pattern in PATTERNS:
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


async def _amain(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="reset-posthog-code-usage",
        description="Reset PostHog Code usage counters in the LLM gateway Redis for every user.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Count keys without deleting.")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.redis_url:
        logger.error("redis_url_not_configured")
        return 1

    redis: Redis = Redis.from_url(settings.redis_url)
    deleted = await reset_usage(redis, dry_run=args.dry_run)

    mode = "DRY RUN" if args.dry_run else "EXECUTED"
    print(f"[{mode}] reset posthog_code usage: {deleted} keys")
    return 0


def main() -> None:
    sys.exit(asyncio.run(_amain(sys.argv[1:])))


if __name__ == "__main__":
    main()
