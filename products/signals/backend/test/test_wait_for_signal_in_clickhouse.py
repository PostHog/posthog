import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone

from temporalio.testing import ActivityEnvironment

from products.signals.backend.temporal.signal_queries import (
    WaitForClickHouseInput,
    WaitForClickHouseMode,
    WaitForClickHouseSignal,
    wait_for_signal_in_clickhouse_activity,
)

MODULE = "products.signals.backend.temporal.signal_queries"

TEAM_ID = 1


def _signals(count: int) -> list[WaitForClickHouseSignal]:
    now = timezone.now()
    return [WaitForClickHouseSignal(signal_id=str(uuid.uuid4()), timestamp=now) for _ in range(count)]


def _ch_result(count: int) -> SimpleNamespace:
    return SimpleNamespace(results=[[count]])


def _store_returning(offset: timedelta | None):
    # Answers the lookup with each document's expected timestamp shifted by `offset`
    # (None means "never emitted" for every document).
    async def lookup(documents, *, team_id):
        if offset is None:
            return dict.fromkeys(documents)
        return {d: timezone.now() + offset for d in documents}

    return lookup


async def _store_raising(documents, *, team_id):
    raise RuntimeError("worker down")


def _team_model_mock() -> MagicMock:
    team = MagicMock(name="Team")
    team.objects.aget = AsyncMock(return_value=MagicMock(pk=TEAM_ID))
    return team


async def _run(
    signals: list[WaitForClickHouseSignal],
    max_wait_time_seconds: int = 600,
    mode: WaitForClickHouseMode = WaitForClickHouseMode.CH_CONFIRMED,
) -> None:
    env = ActivityEnvironment()
    await env.run(
        wait_for_signal_in_clickhouse_activity,
        WaitForClickHouseInput(
            team_id=TEAM_ID, signals=signals, max_wait_time_seconds=max_wait_time_seconds, mode=mode
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,expected_ch_queries",
    [
        pytest.param(WaitForClickHouseMode.OPTIMISTIC, 0, id="optimistic_trusts_store_and_skips_clickhouse"),
        pytest.param(WaitForClickHouseMode.CH_CONFIRMED, 1, id="ch_confirmed_runs_single_confirm"),
    ],
)
async def test_store_confirmation_short_circuits(mode, expected_ch_queries):
    signals = _signals(2)
    with (
        patch(f"{MODULE}.Team", _team_model_mock()),
        patch(f"{MODULE}.async_get_recently_seen_documents", side_effect=_store_returning(timedelta(0))) as store,
        patch(f"{MODULE}.execute_hogql_query_with_retry", AsyncMock(return_value=_ch_result(2))) as ch,
        patch(f"{MODULE}.asyncio.sleep", AsyncMock()) as sleep,
    ):
        await _run(signals, mode=mode)

    # The store confirmed on the first attempt: optimistic mode must return without
    # touching ClickHouse at all, ch_confirmed with exactly one confirm query — and
    # neither should sleep through a poll interval.
    assert ch.await_count == expected_ch_queries
    assert store.call_count == 1
    assert sleep.await_count == 0


@pytest.mark.asyncio
async def test_ch_only_mode_never_consults_the_store():
    signals = _signals(1)
    with (
        patch(f"{MODULE}.Team", _team_model_mock()),
        patch(f"{MODULE}.async_get_recently_seen_documents", side_effect=_store_returning(timedelta(0))) as store,
        patch(f"{MODULE}.execute_hogql_query_with_retry", AsyncMock(return_value=_ch_result(1))) as ch,
        patch(f"{MODULE}.asyncio.sleep", AsyncMock()) as sleep,
    ):
        await _run(signals, mode=WaitForClickHouseMode.CH_ONLY)

    # ch_only is for waits the store can't see (soft-deletes): ClickHouse polls from
    # the first attempt with no grace-period deferral, and the store is never queried.
    assert ch.await_count == 1
    assert store.call_count == 0
    assert sleep.await_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "store_behavior",
    [
        pytest.param(_store_returning(None), id="never_emitted"),
        pytest.param(_store_returning(timedelta(hours=-1)), id="stale_record_from_earlier_emission"),
        pytest.param(_store_raising, id="store_unavailable"),
    ],
)
async def test_unconfirmed_store_defers_clickhouse_until_grace_period_elapses(store_behavior):
    signals = _signals(1)
    with (
        patch(f"{MODULE}.Team", _team_model_mock()),
        patch(f"{MODULE}.async_get_recently_seen_documents", side_effect=store_behavior) as store,
        patch(f"{MODULE}.execute_hogql_query_with_retry", AsyncMock(return_value=_ch_result(1))) as ch,
        patch(f"{MODULE}.asyncio.sleep", AsyncMock()),
        patch(f"{MODULE}.metrics.increment_ch_wait_timeout") as timeout_metric,
    ):
        await _run(signals, max_wait_time_seconds=660)

    # The store never confirms, so ClickHouse must not be touched during the 5-minute
    # grace period, then must run on the every-3rd-attempt fallback — its positive
    # answer ends the wait. With 10s attempts the first eligible fallback is attempt 32
    # (>=300s elapsed and on cadence), so exactly 33 store polls precede the single
    # ClickHouse query; an early ClickHouse poll would return sooner and shrink the
    # store count, and a store-gated ClickHouse would never run and time out instead.
    assert ch.await_count == 1
    assert store.call_count == 33
    timeout_metric.assert_not_called()


@pytest.mark.asyncio
async def test_gives_up_after_max_wait_and_records_timeout():
    signals = _signals(1)
    with (
        patch(f"{MODULE}.Team", _team_model_mock()),
        patch(f"{MODULE}.async_get_recently_seen_documents", side_effect=_store_returning(None)),
        patch(f"{MODULE}.execute_hogql_query_with_retry", AsyncMock(return_value=_ch_result(0))) as ch,
        patch(f"{MODULE}.asyncio.sleep", AsyncMock()),
        patch(f"{MODULE}.metrics.increment_ch_wait_timeout") as timeout_metric,
    ):
        await _run(signals, max_wait_time_seconds=30)

    # A wait shorter than the grace period still checks ClickHouse once, on the final
    # attempt, before giving up and recording the timeout.
    assert ch.await_count == 1
    timeout_metric.assert_called_once()
