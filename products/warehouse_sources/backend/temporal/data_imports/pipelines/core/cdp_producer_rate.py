import asyncio
from collections.abc import Awaitable, Callable

from prometheus_client import Counter

from posthog.egress.limiter.outbound import OutboundRateLimiter, get_outbound_rate_limiter
from posthog.egress.limiter.policies import RatePolicy, register_policy

_RATE_DOMAIN = "warehouse_cdp_producer"
ROWS_PER_SECOND = 2000.0

CDP_PRODUCER_THROTTLE_WAITS_TOTAL = Counter(
    "warehouse_cdp_producer_throttle_waits_total",
    "Warehouse CDP producer waits for the table rate limit",
    labelnames=["team_id"],
)


def rate_limits(rows_per_second: float) -> tuple[int, float]:
    if rows_per_second >= 1:
        return int(rows_per_second), 1.0
    return 1, 1.0 / rows_per_second


register_policy(_RATE_DOMAIN, RatePolicy(limits=(rate_limits(ROWS_PER_SECOND),), in_memory_divider=1, reserve={}))


class RowThrottle:
    def __init__(
        self,
        *,
        team_id: int,
        limiter: OutboundRateLimiter | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._team_id = team_id
        self._key = f"{_RATE_DOMAIN}:team:{team_id}"
        self._limiter = limiter if limiter is not None else get_outbound_rate_limiter()
        self._sleep = sleep
        self._count, self._period = rate_limits(ROWS_PER_SECOND)
        self._block = max(1, min(self._count // 10, 500))
        self._allowance = 0

    async def acquire_row(self) -> None:
        if self._allowance == 0:
            while not await self._limiter.acquire(self._key, self._block, source="warehouse_cdp_producer"):
                CDP_PRODUCER_THROTTLE_WAITS_TOTAL.labels(team_id=str(self._team_id)).inc()
                await self._sleep(max(self._block * self._period / self._count, 0.05))
            self._allowance = self._block
        self._allowance -= 1
