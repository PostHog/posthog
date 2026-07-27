"""Signals credit quota enforcement.

Lives in its own module (not `billing.py`) to avoid a circular import: `billing.py` is imported by
`posthog.tasks.usage_report`, which `ee.billing.quota_limiting` imports in turn.
"""

import structlog
from temporalio import activity

from posthog.temporal.common.metrics import get_metric_meter

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited

logger = structlog.get_logger(__name__)


def _record_failed_open() -> None:
    # Emit the meter directly rather than via products.signals.backend.temporal.metrics: importing
    # that package runs its __init__, which imports buffer.py, which imports this module (cycle).
    if not activity.in_activity():
        return
    get_metric_meter().create_counter(
        "signals_quota_check_failed_open_total",
        "Signals quota checks that errored and failed open, bypassing enforcement",
    ).add(1)


def is_team_signals_quota_limited(team_api_token: str) -> bool:
    """Whether a team is currently over its Signals credits quota.

    Fails open on a quota-limiter read error so an infra blip lets work through rather than stalling.
    Records `signals_quota_check_failed_open_total` so the bypass is alertable.
    Synchronous (Redis read); wrap in `sync_to_async` when calling from async code.
    """
    try:
        return is_team_limited(
            team_api_token, QuotaResource.SIGNALS_CREDITS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )
    except Exception:
        logger.warning("signals_quota_check_failed_open", exc_info=True)
        _record_failed_open()
        return False
