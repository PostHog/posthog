import uuid

import pytest

from asgiref.sync import async_to_sync
from temporalio.testing import ActivityEnvironment

from products.tasks.backend.logic.stream.redis_stream import TaskRunRedisStream, get_task_run_stream_key
from products.tasks.backend.temporal.process_task.activities.check_agent_active_flag import (
    CheckAgentActiveFlagInput,
    check_agent_active_flag,
)


@pytest.mark.django_db(transaction=True)
class TestCheckAgentActiveFlag:
    @pytest.mark.parametrize(
        "flag_value, expected",
        [
            # An ingested session update left the agent mid-turn.
            (True, True),
            # A turn-complete event was ingested since; this is the loss-proof record the
            # workflow falls back on when its fire-and-forget signal never arrived.
            (False, False),
            # No flag: the run never went through an ingest plane.
            (None, None),
        ],
    )
    def test_reads_the_ingest_plane_flag(
        self, activity_environment: ActivityEnvironment, flag_value: bool | None, expected: bool | None
    ) -> None:
        run_id = str(uuid.uuid4())
        if flag_value is not None:
            stream = TaskRunRedisStream(get_task_run_stream_key(run_id))
            async_to_sync(stream.set_agent_active)(flag_value)

        async def _run() -> bool | None:
            return await activity_environment.run(
                check_agent_active_flag, CheckAgentActiveFlagInput(run_id=run_id, team_id=1)
            )

        result = async_to_sync(_run)()

        assert result is expected
