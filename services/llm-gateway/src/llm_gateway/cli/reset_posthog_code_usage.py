"""Reset PostHog Code usage / rate-limit counters in the gateway Redis.

Two kinds of limit can be reset:

* cost     — the posthog_code per-user cost counters (burst + sustained), and
             optionally the product-wide aggregate cost pool (--product-total).
* request  — the per-user request-rate counters (burst + sustained). These are
             keyed by user id alone and are NOT product-scoped, so resetting
             them lifts the user's request-rate limit across every product.

By default both kinds are reset; pass --cost or --request to narrow. With no
--user-id every user is reset; pass one or more --user-id to scope it.

The key shapes live in `rate_limiting/usage_reset.py`, shared with the staff
admin endpoint in `api/admin.py`.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import structlog
from redis.asyncio import Redis

from llm_gateway.config import get_settings

# Re-exported so existing callers/tests can import the key helpers from here.
from llm_gateway.rate_limiting.usage_reset import (
    cost_patterns,
    product_patterns,
    request_patterns,
    reset_keys,
)

__all__ = ["cost_patterns", "product_patterns", "request_patterns", "reset_keys"]

logger = structlog.get_logger(__name__)


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
