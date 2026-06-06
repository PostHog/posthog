from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, patch

from temporalio.testing import ActivityEnvironment

from products.signals.backend.temporal.signal_queries import (
    WaitForClickHouseInput,
    WaitForClickHouseSignal,
    wait_for_signal_in_clickhouse_activity,
)

_QUERY = "products.signals.backend.temporal.signal_queries.execute_hogql_query_with_retry"
_AGET = "products.signals.backend.temporal.signal_queries.Team.objects.aget"
_SLEEP = "products.signals.backend.temporal.signal_queries.asyncio.sleep"


def _input(max_wait_time_seconds: int) -> WaitForClickHouseInput:
    return WaitForClickHouseInput(
        team_id=1,
        signals=[WaitForClickHouseSignal(signal_id="sig-a", timestamp=datetime(2026, 1, 1, tzinfo=UTC))],
        max_wait_time_seconds=max_wait_time_seconds,
    )


def _count(n: int) -> SimpleNamespace:
    return SimpleNamespace(results=[[n]])


@pytest.mark.asyncio
async def test_returns_as_soon_as_signals_land():
    query = AsyncMock(side_effect=[_count(0), _count(1)])
    with (
        patch(_QUERY, query),
        patch(_AGET, AsyncMock(return_value=object())),
        patch(_SLEEP, AsyncMock()),
    ):
        await ActivityEnvironment().run(wait_for_signal_in_clickhouse_activity, _input(120))
    assert query.await_count == 2


@pytest.mark.asyncio
async def test_gives_up_at_deadline_without_raising():
    # When signals never land, the activity must reach its graceful return before the
    # caller's start_to_close timeout — i.e. bounded by max_wait_time, never an infinite poll.
    clock = {"now": datetime(2026, 6, 1, tzinfo=UTC)}

    def fake_now() -> datetime:
        return clock["now"]

    async def fake_sleep(seconds: float) -> None:
        clock["now"] += timedelta(seconds=seconds)

    query = AsyncMock(return_value=_count(0))
    with (
        patch(_QUERY, query),
        patch(_AGET, AsyncMock(return_value=object())),
        patch("django.utils.timezone.now", fake_now),
        patch(_SLEEP, fake_sleep),
    ):
        await ActivityEnvironment().run(wait_for_signal_in_clickhouse_activity, _input(60))

    # 60s budget / 10s poll interval → a handful of polls, then a clean return (no raise).
    assert 2 <= query.await_count <= 8
    assert clock["now"] >= datetime(2026, 6, 1, tzinfo=UTC) + timedelta(seconds=60)
