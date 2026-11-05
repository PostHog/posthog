import math
from collections.abc import Sequence

import pytest
from unittest.mock import AsyncMock, Mock, call, patch

from posthog.egress.limiter.outbound import OutboundRateLimiter
from posthog.egress.limiter.policies import resolve_policy

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer import ProduceCheckpoint
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer_rate import (
    RowThrottle,
    aget_rows_per_second,
    rate_limits,
    resolve_rows_per_second,
)

DEFAULT_RATE = 2000.0


@pytest.mark.parametrize(
    "payload,expected",
    [
        (None, DEFAULT_RATE),
        ("invalid payload", DEFAULT_RATE),
        ({}, DEFAULT_RATE),
        ({"default_rows_per_second": 100, "overrides": {"table": 50}}, 50),
        ({"default_rows_per_second": 100, "overrides": {"another": 50}}, 100),
        ({"default_rows_per_second": 100}, 100),
        ({"overrides": {"table": 50}}, 50),
        ({"default_rows_per_second": 100, "overrides": {"table": "50"}}, 100),
        ({"default_rows_per_second": 100, "overrides": {"table": True}}, 100),
        ({"default_rows_per_second": 100, "overrides": {"table": 0}}, 100),
        ({"default_rows_per_second": 100, "overrides": {"table": -1}}, 100),
        ({"default_rows_per_second": 100, "overrides": {"table": float("nan")}}, 100),
        ({"default_rows_per_second": 100, "overrides": "invalid"}, 100),
        ({"default_rows_per_second": "100"}, DEFAULT_RATE),
        ({"default_rows_per_second": True}, DEFAULT_RATE),
        ({"default_rows_per_second": 0}, DEFAULT_RATE),
        ({"default_rows_per_second": -1}, DEFAULT_RATE),
        ({"default_rows_per_second": float("nan")}, DEFAULT_RATE),
        ({"default_rows_per_second": float("inf")}, DEFAULT_RATE),
        ({"default_rows_per_second": 10**1000}, DEFAULT_RATE),
        ({"default_rows_per_second": 100, "overrides": {"table": 0.5}}, 0.5),
        ({"default_rows_per_second": 100, "overrides": {"table": 0.001}}, 0.01),
        ({"default_rows_per_second": 0.001}, 0.01),
    ],
)
def test_resolve_rows_per_second(payload: object, expected: float) -> None:
    assert resolve_rows_per_second("table", payload) == expected


@pytest.mark.asyncio
async def test_aget_rows_per_second_uses_default_when_flag_fetch_fails() -> None:
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer_rate.posthoganalytics.get_feature_flag_payload",
        side_effect=RuntimeError("flag service unavailable"),
    ):
        assert await aget_rows_per_second("table") == DEFAULT_RATE


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
    throttle = RowThrottle(team_id=1, table_id="table", limiter=limiter, sleep=sleep, clock=lambda: 0.0)

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer_rate.aget_rows_per_second",
        new=AsyncMock(return_value=rate),
    ):
        for _ in range(rows):
            await throttle.acquire_row()

    sleep.assert_awaited_once_with(delay)
    assert limiter.acquire.await_args_list == [
        call("warehouse_cdp_producer:table:table", block, source="warehouse_cdp_producer")
    ] * (math.ceil(rows / block) + 1)
    policy = resolve_policy("warehouse_cdp_producer:table:table")
    assert policy.limits == (rate_limits(rate),)
    assert policy.reserve == {}
    assert policy.in_memory_divider == 1


@pytest.mark.asyncio
async def test_row_throttle_refreshes_the_live_rate() -> None:
    limiter = Mock(spec=OutboundRateLimiter)
    limiter.acquire = AsyncMock(return_value=True)
    clock = Mock(return_value=0.0)
    throttle = RowThrottle(team_id=1, table_id="refresh_table", limiter=limiter, clock=clock)

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer_rate.aget_rows_per_second",
        new=AsyncMock(side_effect=[1.0, 0.5]),
    ) as read_rate:
        await throttle.acquire_row()
        clock.return_value = 59.0
        await throttle.acquire_row()
        assert read_rate.await_count == 1
        clock.return_value = 60.0
        await throttle.acquire_row()

    assert read_rate.await_count == 2
    assert resolve_policy("warehouse_cdp_producer:table:refresh_table").limits == ((1, 2.0),)
