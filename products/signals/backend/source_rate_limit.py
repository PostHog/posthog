"""Per-project, per-source cap on signal emission.

`emit_signal` checks this gate before any Temporal workflow or LLM call, so one project and source
cannot push an unbounded burst of signals through grouping. Each `(team_id, source_product,
source_type)` has two token buckets: an hourly one and a rolling-day one. A signal must get a token
from both.

Enforcement sits behind `SIGNALS_SOURCE_RATE_LIMIT_ENFORCEMENT_FLAG`. With the flag off the gate
still charges the buckets and reports would-drops, but lets every signal through. A would-drop
does not take a token, the same as a real drop, so the dark-launch numbers match what enforcement
would do. The gate fails open when Redis cannot answer, like `quota.py` and `daily_limit.py`.
"""

from enum import StrEnum

import structlog
import posthoganalytics
from prometheus_client import Counter

from posthog.token_bucket import BucketUnavailable, Budget, consume, refund

logger = structlog.get_logger(__name__)

SIGNALS_SOURCE_RATE_LIMIT_ENFORCEMENT_FLAG = "signals-source-rate-limit-enforcement"

HOURLY_BUDGET = Budget(burst=200, per_hour=200)
# A rolling day rather than a calendar day, which is acceptable for an abuse cap.
DAILY_BUDGET = Budget(burst=1000, per_hour=42)

SOURCE_RATE_LIMITED = Counter(
    "signals_source_rate_limited_total",
    "Signals over their per-project, per-source rate cap, by whether the gate dropped them",
    labelnames=["source_product", "window", "enforced"],
)
SOURCE_RATE_CHECK_FAILED_OPEN = Counter(
    "signals_source_rate_check_failed_open_total",
    "Signals source rate checks that could not reach Redis and let the signal through",
)


class SourceRateWindow(StrEnum):
    HOUR = "hour"
    DAY = "day"


def _bucket_key(team_id: int, source_product: str, source_type: str, window: SourceRateWindow) -> str:
    return f"signals:source_rate:{team_id}:{source_product}:{source_type}:{window}"


def source_rate_limit_exceeded(team_id: int, source_product: str, source_type: str) -> SourceRateWindow | None:
    """Charge one signal to the source's buckets. Return the window that is out of tokens, or None.

    The hourly bucket goes first. When the daily bucket then refuses, the hourly token goes back,
    because the signal does not enter the pipeline under enforcement. Blocking Redis I/O; wrap in
    `asyncio.to_thread` from async code.
    """
    hourly_key = _bucket_key(team_id, source_product, source_type, SourceRateWindow.HOUR)
    hourly = consume(hourly_key, HOURLY_BUDGET)
    if isinstance(hourly, BucketUnavailable):
        _record_fail_open(team_id, source_product, source_type, hourly)
        return None
    if not hourly.allowed:
        return SourceRateWindow.HOUR

    daily = consume(_bucket_key(team_id, source_product, source_type, SourceRateWindow.DAY), DAILY_BUDGET)
    if isinstance(daily, BucketUnavailable):
        _record_fail_open(team_id, source_product, source_type, daily)
        return None
    if not daily.allowed:
        refund(hourly_key, HOURLY_BUDGET)
        return SourceRateWindow.DAY
    return None


def _record_fail_open(team_id: int, source_product: str, source_type: str, unavailable: BucketUnavailable) -> None:
    logger.warning(
        "signals_source_rate_check_failed_open",
        team_id=team_id,
        source_product=source_product,
        source_type=source_type,
        error=unavailable.error,
    )
    SOURCE_RATE_CHECK_FAILED_OPEN.inc()


def source_rate_limit_enforcement_enabled(organization_id: str) -> bool:
    """Whether the gate drops signals for this org, rather than only reporting would-drops.

    Org-keyed like `self-driving-quota-enforcement`. A flag-read error means no enforcement, so a
    flag outage cannot stop the fleet's signals. Blocking network I/O; wrap in `asyncio.to_thread`.
    """
    try:
        return (
            posthoganalytics.feature_enabled(
                SIGNALS_SOURCE_RATE_LIMIT_ENFORCEMENT_FLAG,
                organization_id,
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
            )
            is True
        )
    except Exception:
        logger.warning("signals_source_rate_limit_flag_check_failed", exc_info=True)
        return False


def record_source_rate_limited(source_product: str, window: SourceRateWindow, *, enforced: bool) -> None:
    SOURCE_RATE_LIMITED.labels(source_product=source_product, window=window, enforced=str(enforced).lower()).inc()
