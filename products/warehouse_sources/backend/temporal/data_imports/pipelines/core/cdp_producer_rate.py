import math
import time
import asyncio
from collections.abc import Awaitable, Callable

import structlog
import posthoganalytics
from prometheus_client import Counter

from posthog.egress.limiter.outbound import OutboundRateLimiter, get_outbound_rate_limiter
from posthog.egress.limiter.policies import RatePolicy, register_policy

logger = structlog.get_logger(__name__)

WAREHOUSE_CDP_PRODUCER_RATE_FLAG = "warehouse-cdp-producer-rate-limits"
_FLAG_DISTINCT_ID = "internal_warehouse_cdp_producer"
_RATE_DOMAIN = "warehouse_cdp_producer"
_MIN_ROWS_PER_SECOND = 0.01
_DEFAULT_ROWS_PER_SECOND = 2000.0
_live_rates: dict[str, float] = {}

CDP_PRODUCER_THROTTLE_WAITS_TOTAL = Counter(
    "warehouse_cdp_producer_throttle_waits_total",
    "Warehouse CDP producer waits for the table rate limit",
    labelnames=["team_id"],
)


def _valid_rate(value: object, field: str) -> float | None:
    rate: float | None = None
    if isinstance(value, int | float) and not isinstance(value, bool):
        try:
            rate = float(value)
        except (TypeError, ValueError, OverflowError):
            pass
    if rate is None or not math.isfinite(rate) or rate <= 0:
        logger.warning("warehouse_cdp_producer.invalid_rate", field=field, value_type=type(value).__name__)
        return None
    return rate


def resolve_rows_per_second(table_id: str, payload: object) -> float:
    if not isinstance(payload, dict):
        if payload is not None:
            logger.warning("warehouse_cdp_producer.invalid_rate_payload", value_type=type(payload).__name__)
        return _DEFAULT_ROWS_PER_SECOND

    default_rate = _DEFAULT_ROWS_PER_SECOND
    if "default_rows_per_second" in payload:
        default_rate = _valid_rate(payload["default_rows_per_second"], "default_rows_per_second") or default_rate

    if "overrides" in payload:
        overrides = payload["overrides"]
        if not isinstance(overrides, dict):
            logger.warning("warehouse_cdp_producer.invalid_rate_overrides", value_type=type(overrides).__name__)
        elif table_id in overrides:
            override_rate = _valid_rate(overrides[table_id], "overrides")
            if override_rate is not None:
                return max(_MIN_ROWS_PER_SECOND, override_rate)

    return max(_MIN_ROWS_PER_SECOND, default_rate)


def rate_limits(rows_per_second: float) -> tuple[int, float]:
    if rows_per_second >= 1:
        return int(rows_per_second), 1.0
    return 1, 1.0 / rows_per_second


async def aget_rows_per_second(table_id: str) -> float:
    try:
        payload: object = await asyncio.to_thread(
            posthoganalytics.get_feature_flag_payload, WAREHOUSE_CDP_PRODUCER_RATE_FLAG, _FLAG_DISTINCT_ID
        )
    except Exception:
        logger.warning("warehouse_cdp_producer.rate_flag_fetch_failed", exc_info=True)
        payload = None
    return resolve_rows_per_second(table_id, payload)


def _rate_policy(key: str) -> RatePolicy:
    rate = _live_rates.get(key, _DEFAULT_ROWS_PER_SECOND)
    return RatePolicy(limits=(rate_limits(rate),), in_memory_divider=1, reserve={})


register_policy(_RATE_DOMAIN, _rate_policy)


class RowThrottle:
    def __init__(
        self,
        *,
        team_id: int,
        table_id: str,
        limiter: OutboundRateLimiter | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        refresh_interval_seconds: float = 60.0,
    ) -> None:
        self._team_id = team_id
        self._table_id = table_id
        self._key = f"{_RATE_DOMAIN}:table:{table_id}"
        self._limiter = limiter if limiter is not None else get_outbound_rate_limiter()
        self._sleep = sleep
        self._clock = clock
        self._refresh_interval_seconds = refresh_interval_seconds
        self._last_refresh: float | None = None
        self._rate = _DEFAULT_ROWS_PER_SECOND
        self._allowance = 0

    async def refresh(self) -> None:
        self._rate = await aget_rows_per_second(self._table_id)
        _live_rates[self._key] = self._rate
        self._last_refresh = self._clock()

    async def acquire_row(self) -> None:
        if self._allowance == 0:
            if self._last_refresh is None or self._clock() - self._last_refresh >= self._refresh_interval_seconds:
                await self.refresh()
            count, period = rate_limits(self._rate)
            block = max(1, min(count // 10, 500))
            while not await self._limiter.acquire(self._key, block, source="warehouse_cdp_producer"):
                CDP_PRODUCER_THROTTLE_WAITS_TOTAL.labels(team_id=str(self._team_id)).inc()
                await self._sleep(max(block * period / count, 0.05))
            self._allowance = block
        self._allowance -= 1
