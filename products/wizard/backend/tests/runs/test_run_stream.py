import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import async_to_sync
from redis.exceptions import ConnectionError as RedisConnectionError

from posthog.sync import database_sync_to_async

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.contracts import (
    CreateWizardRunInput,
    LocalFolderWorkspace,
    UpdateWizardRunTaskInput,
)
from products.wizard.backend.facade.enums import WizardRunEnvironment, WizardTaskStatus
from products.wizard.backend.presentation.runs.stream import wizard_run_event_stream
from products.wizard.backend.presentation.sessions import config


@pytest.mark.django_db(transaction=True)
def test_run_stream_reads_committed_state_and_closes_subscription(team, user) -> None:
    run = wizard_facade.create_run(
        CreateWizardRunInput(
            team_id=team.id,
            created_by_id=user.id,
            program_id="posthog-integration",
            environment=WizardRunEnvironment.LOCAL,
            workspace=LocalFolderWorkspace(project_name="example-project"),
        )
    )
    subscription = MagicMock()
    subscription.__aenter__ = AsyncMock(return_value=subscription)
    subscription.__aexit__ = AsyncMock()
    subscription.subscribe = AsyncMock()
    subscription.get_message = AsyncMock(return_value={"type": "message", "data": b"{}"})

    async def consume() -> None:
        stream = wizard_run_event_stream(team.id, run.id)
        try:
            initial = json.loads((await anext(stream)).removeprefix(b"data: "))
            assert initial["tasks"] == []
            assert initial["status"] == "running"
            assert "id" not in initial
            assert "team_id" not in initial

            await database_sync_to_async(wizard_facade.update_run_task_list, thread_sensitive=False)(
                team.id, run.id, (UpdateWizardRunTaskInput(title="Install SDK", status=WizardTaskStatus.RUNNING),)
            )
            updated = json.loads((await anext(stream)).removeprefix(b"data: "))
            assert updated["tasks"][0]["name"] == "Install SDK"
            assert updated["tasks"][0]["started_at"] is not None

            subscription.get_message.return_value = None
            with patch.object(config, "SSE_HEARTBEAT_INTERVAL_SECONDS", 0):
                assert await anext(stream) == b": ping\n\n"
            with patch.object(config, "SSE_MAX_DURATION_SECONDS", 0):
                assert await anext(stream) == b"event: end\ndata: reconnect\n\n"
        finally:
            await stream.aclose()

    with (
        patch("products.wizard.backend.logic.runs.pubsub.get_async_client") as async_client,
        patch("products.wizard.backend.logic.runs.pubsub.get_client") as client,
    ):
        async_client.return_value.pubsub.return_value = subscription
        client.return_value.publish.side_effect = RedisConnectionError("unavailable")
        async_to_sync(consume)()
    subscription.subscribe.assert_awaited_once_with(f"wizard_runs:team:{team.id}:run:{run.id}")
    subscription.__aexit__.assert_awaited_once()
