from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, patch

import temporalio.exceptions
from temporalio.testing import ActivityEnvironment

from posthog.hogql import ast

from products.signals.backend.temporal.signal_queries import (
    WAIT_INSERTED_AT_LOOKBACK,
    WaitForClickHouseInput,
    WaitForClickHouseSignal,
    wait_for_signal_in_clickhouse_activity,
)

_CLICKHOUSE_BOUNDARY = "products.signals.backend.temporal.clickhouse.execute_hogql_query"


def _signals(timestamp: datetime) -> list[WaitForClickHouseSignal]:
    return [WaitForClickHouseSignal(signal_id="doc-1", timestamp=timestamp)]


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_threshold_is_anchored_to_signal_timestamps_not_wall_clock(ateam) -> None:
    # A signal emitted long before the wait starts (slow emission / activity retry) still has to be
    # found: anchoring the inserted_at lower bound to wall-clock `now()` would push it past the
    # signal's own (old) inserted_at and exclude a row that genuinely arrived.
    emitted_at = datetime.now(UTC) - timedelta(minutes=45)
    captured: dict[str, ast.Constant] = {}

    def fake_query(*, placeholders: dict[str, ast.Constant], **kwargs: object) -> SimpleNamespace:
        captured.update(placeholders)
        return SimpleNamespace(results=[[1]])

    with patch(_CLICKHOUSE_BOUNDARY, side_effect=fake_query):
        await ActivityEnvironment().run(
            wait_for_signal_in_clickhouse_activity,
            WaitForClickHouseInput(team_id=ateam.pk, signals=_signals(emitted_at)),
        )

    assert captured["inserted_at_threshold"].value == emitted_at - WAIT_INSERTED_AT_LOOKBACK


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_raises_when_signals_never_appear(ateam) -> None:
    # Timing out must raise so the activity's retry policy engages — silently returning would let
    # the pipeline proceed with signals that never landed and produce a corrupt report.
    with (
        patch(_CLICKHOUSE_BOUNDARY, return_value=SimpleNamespace(results=[[0]])),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        with pytest.raises(temporalio.exceptions.ApplicationError) as exc_info:
            await ActivityEnvironment().run(
                wait_for_signal_in_clickhouse_activity,
                WaitForClickHouseInput(
                    team_id=ateam.pk,
                    signals=_signals(datetime.now(UTC)),
                    max_wait_time_seconds=10,
                ),
            )

    assert exc_info.value.type == "SignalsClickHouseWaitTimeout"
