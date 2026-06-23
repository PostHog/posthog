"""Signals credit quota enforcement.

Signals is billed on outcomes (see `billing.py`) and enforces its credit quota in its own
pipeline rather than at the LLM gateway. The expensive stages — report generation and
implementation auto-start — gate on `is_team_signals_quota_limited` before spending, so a team
that is out of Signals credits stops accruing both infra cost and new billable implementation PRs.

This lives in its own module (not `billing.py`) on purpose: `billing.py` is imported by
`posthog.tasks.usage_report`, which `ee.billing.quota_limiting` imports in turn — importing the
quota helpers from `billing.py` would close that loop into a circular import.
"""

import structlog

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited

logger = structlog.get_logger(__name__)


def is_team_signals_quota_limited(team_api_token: str) -> bool:
    """Whether a team is currently over its Signals credits quota.

    Reads the same Redis quota-limiter zset the billing task populates for every `QuotaResource`.
    Synchronous (Redis read); wrap in `database_sync_to_async` when calling from async pipeline code.

    Fails open: if the quota-limiter read errors (e.g. Redis blip) we return False so a quota-infra
    hiccup degrades to letting work through rather than stalling report generation. Enforcement is
    eventually consistent regardless — the zset is only refreshed periodically.
    """
    try:
        return is_team_limited(
            team_api_token, QuotaResource.SIGNALS_CREDITS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )
    except Exception:
        logger.warning("signals_quota_check_failed_open", exc_info=True)
        return False
