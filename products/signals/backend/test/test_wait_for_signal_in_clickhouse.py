import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone

from temporalio.testing import ActivityEnvironment

from products.signals.backend.temporal.signal_queries import (
    WaitForClickHouseInput,
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


async def _run(signals: list[WaitForClickHouseSignal], max_wait_time_seconds: int = 600) -> None:
    env = ActivityEnvironment()
    await env.run(
        wait_for_signal_in_clickhouse_activity,
        WaitForClickHouseInput(team_id=TEAM_ID, signals=signals, max_wait_time_seconds=max_wait_time_seconds),
    )


@pytest.mark.asyncio
async def test_store_confirmation_short_circuits_to_single_clickhouse_confirm():
    signals = _signals(2)
    with (
        patch(f"{MODULE}.Team", _team_model_mock()),
        patch(f"{MODULE}.async_get_recently_seen_documents", side_effect=_store_returning(timedelta(0))) as store,
        patch(f"{MODULE}.execute_hogql_query_with_retry", AsyncMock(return_value=_ch_result(2))) as ch,
        patch(f"{MODULE}.asyncio.sleep", AsyncMock()) as sleep,
    ):
        await _run(signals)

    # The store confirmed on the first attempt, so ClickHouse is queried once, off the
    # fallback cadence, and the activity returns without sleeping through poll intervals.
    assert ch.await_count == 1
    assert store.call_count == 1
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
async def test_unconfirmed_store_still_reaches_clickhouse_on_fallback_cadence(store_behavior):
    signals = _signals(1)
    with (
        patch(f"{MODULE}.Team", _team_model_mock()),
        patch(f"{MODULE}.async_get_recently_seen_documents", side_effect=store_behavior) as store,
        patch(f"{MODULE}.execute_hogql_query_with_retry", AsyncMock(return_value=_ch_result(1))) as ch,
        patch(f"{MODULE}.asyncio.sleep", AsyncMock()),
        patch(f"{MODULE}.metrics.increment_ch_wait_timeout") as timeout_metric,
    ):
        await _run(signals, max_wait_time_seconds=30)

    # The store never confirms, so ClickHouse runs only on the every-3rd-attempt
    # fallback — but it must run, and its positive answer must end the wait.
    assert ch.await_count == 1
    assert store.call_count == 3
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

    assert ch.await_count >= 1
    timeout_metric.assert_called_once()
