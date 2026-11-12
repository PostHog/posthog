import math
from collections.abc import Sequence

import pytest
from unittest.mock import AsyncMock, Mock, call, patch

from posthog.egress.limiter.outbound import OutboundRateLimiter
from posthog.egress.limiter.policies import resolve_policy

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer import ProduceCheckpoint
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer_rate import (
    ROWS_PER_SECOND,
    RowThrottle,
    rate_limits,
)


@pytest.mark.parametrize("rate,expected", [(2000, (2000, 1.0)), (1, (1, 1.0)), (0.5, (1, 2.0))])
def test_rate_limits(rate: float, expected: tuple[int, float]) -> None:
    assert rate_limits(rate) == expected


@pytest.mark.parametrize(
    "details,expected",
    [
        (("file", 3), ProduceCheckpoint(file_path="file", rows_done=3)),
        (["file", 0], ProduceCheckpoint(file_path="file", rows_done=0)),
        ((), None),
        (("file",), None),
        (("file", 3, "extra"), None),
        (("file", "3"), None),
        (("file", 3.0), None),
        (("file", True), None),
        (("file", -1), None),
        ((123, 3), None),
    ],
)
def test_checkpoint_from_heartbeat_details(details: Sequence[object], expected: ProduceCheckpoint | None) -> None:
    assert ProduceCheckpoint.from_heartbeat_details(details) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rate,rows,block,delay",
    [(2000, 401, 200, 0.1), (10_000, 1001, 500, 0.05), (1, 3, 1, 1.0), (0.5, 3, 1, 2.0)],
)
async def test_row_throttle_waits_and_reserves_blocks(rate: float, rows: int, block: int, delay: float) -> None:
    limiter = Mock(spec=OutboundRateLimiter)
    limiter.acquire = AsyncMock(side_effect=[False] + [True] * math.ceil(rows / block))
    sleep = AsyncMock()
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer_rate.ROWS_PER_SECOND",
        rate,
    ):
        throttle = RowThrottle(team_id=1, limiter=limiter, sleep=sleep)
        for _ in range(rows):
            await throttle.acquire_row()

    sleep.assert_awaited_once_with(delay)
    assert limiter.acquire.await_args_list == [
        call("warehouse_cdp_producer:team:1", block, source="warehouse_cdp_producer")
    ] * (math.ceil(rows / block) + 1)
    policy = resolve_policy("warehouse_cdp_producer:team:1")
    assert policy.limits == (rate_limits(ROWS_PER_SECOND),)
    assert policy.reserve == {}
    assert policy.in_memory_divider == 1
