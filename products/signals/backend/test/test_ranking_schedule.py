import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.client import Client, ScheduleState

from products.signals.backend.ranking import schedule as ranking_schedule
from products.signals.backend.ranking.schedule import (
    INBOX_RANKING_SCORING_SCHEDULE_ID,
    create_inbox_ranking_scoring_schedule,
)


@pytest.mark.asyncio
async def test_an_update_keeps_an_operator_pause() -> None:
    client = MagicMock(spec=Client)
    state = ScheduleState(paused=True, note="Paused by an operator")
    client.get_schedule_handle.return_value.describe = AsyncMock(
        return_value=MagicMock(schedule=MagicMock(state=state))
    )
    with (
        patch.object(ranking_schedule, "a_schedule_exists", return_value=True),
        patch.object(ranking_schedule, "a_create_schedule") as create,
        patch.object(ranking_schedule, "a_update_schedule") as update,
    ):
        await create_inbox_ranking_scoring_schedule(client)

    create.assert_not_awaited()
    client.get_schedule_handle.assert_called_once_with(INBOX_RANKING_SCORING_SCHEDULE_ID)
    assert update.await_args is not None
    assert update.await_args.args[2].state == state
