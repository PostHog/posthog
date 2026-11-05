import math
import time
import asyncio
from collections.abc import Awaitable, Callable

import structlog
from prometheus_client import Counter

from posthog.egress.limiter.outbound import OutboundRateLimiter, get_outbound_rate_limiter
from posthog.egress.limiter.policies import RatePolicy, register_policy
from posthog.models.instance_setting import get_instance_setting
from posthog.settings import CONSTANCE_CONFIG
from posthog.sync import database_sync_to_async_pool

logger = structlog.get_logger(__name__)

_RATE_DOMAIN = "warehouse_cdp_producer"
_MIN_ROWS_PER_SECOND = 0.01
_DEFAULT_ROWS_PER_SECOND = float(CONSTANCE_CONFIG["WAREHOUSE_CDP_PRODUCER_MAX_ROWS_PER_SEC"][0])
_live_rates: dict[str, float] = {}

CDP_PRODUCER_THROTTLE_WAITS_TOTAL = Counter(
    "warehouse_cdp_producer_throttle_waits_total",
    "Warehouse CDP producer waits for the table rate limit",
    labelnames=["team_id"],
)


def parse_rate_overrides(raw: object) -> dict[str, float]:
    if not isinstance(raw, str):
        logger.warning("warehouse_cdp_producer.invalid_rate_override", raw_value=raw)
        return {}

    overrides: dict[str, float] = {}
    for entry in raw.split(","):
        if not entry.strip():
            continue
        table_id, separator, raw_rate = entry.partition(":")
        table_id = table_id.strip()
        try:
            rate = float(raw_rate)
        except (TypeError, ValueError, OverflowError):
            rate = 0.0
        if not separator or not table_id or not math.isfinite(rate) or rate <= 0:
            logger.warning("warehouse_cdp_producer.invalid_rate_override", entry=entry)
            continue
        overrides[table_id] = rate
    return overrides


def resolve_rows_per_second(table_id: str, default_raw: object, overrides_raw: object) -> float:
    overrides = parse_rate_overrides(overrides_raw)
    if table_id in overrides:
        rate = overrides[table_id]
    else:
        try:
            rate = float(default_raw) if isinstance(default_raw, int | float | str) else _DEFAULT_ROWS_PER_SECOND
        except (ValueError, OverflowError):
            rate = _DEFAULT_ROWS_PER_SECOND
        if not math.isfinite(rate) or rate <= 0:
            rate = _DEFAULT_ROWS_PER_SECOND
    return max(_MIN_ROWS_PER_SECOND, rate)


def rate_limits(rows_per_second: float) -> tuple[int, float]:
    if rows_per_second >= 1:
        return int(rows_per_second), 1.0
    return 1, 1.0 / rows_per_second


async def aget_rows_per_second(table_id: str) -> float:
    default_raw = await database_sync_to_async_pool(get_instance_setting)("WAREHOUSE_CDP_PRODUCER_MAX_ROWS_PER_SEC")
    overrides_raw = await database_sync_to_async_pool(get_instance_setting)("WAREHOUSE_CDP_PRODUCER_RATE_OVERRIDES")
    return resolve_rows_per_second(table_id, default_raw, overrides_raw)


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
