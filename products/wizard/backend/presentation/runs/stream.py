from collections.abc import AsyncGenerator
from uuid import UUID

import orjson

from posthog.api.streaming import sse_rotating_event_stream
from posthog.models.scoping import team_scope
from posthog.sync import database_sync_to_async

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.presentation.runs.serializers import WizardRunSerializer, WizardRunTaskListSerializer
from products.wizard.backend.presentation.sessions import config


def _read_run_state(team_id: int, run_id: UUID) -> bytes:
    with team_scope(team_id):
        run = wizard_facade.get_run(team_id, run_id)
    serialized = WizardRunSerializer(run).data
    state = {
        field: serialized[field]
        for field in ("status", "stage", "error_code", "error_message", "updated_at", "started_at", "finished_at")
    }
    state.update(WizardRunTaskListSerializer(run).data)
    return orjson.dumps(state)


async def wizard_run_event_stream(team_id: int, run_id: UUID) -> AsyncGenerator[bytes]:
    async with wizard_facade.subscribe_to_run_updates(team_id, run_id) as subscription:

        async def receive(timeout: float) -> bytes | None:
            message = await subscription.get_message(timeout=timeout)
            if message and message.get("type") == "message":
                return await database_sync_to_async(_read_run_state, thread_sensitive=False)(team_id, run_id)
            return None

        # Subscribe before reading so changes during the read remain queued on the Redis connection.
        yield (
            b"data: " + await database_sync_to_async(_read_run_state, thread_sensitive=False)(team_id, run_id) + b"\n\n"
        )
        async for chunk in sse_rotating_event_stream(
            receive,
            max_duration_seconds=config.SSE_MAX_DURATION_SECONDS,
            heartbeat_interval_seconds=config.SSE_HEARTBEAT_INTERVAL_SECONDS,
        ):
            yield chunk
