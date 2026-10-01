import time
from collections.abc import AsyncGenerator
from uuid import UUID

import orjson

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
    started_at = time.monotonic()
    async with wizard_facade.subscribe_to_run_updates(team_id, run_id) as subscription:
        # Subscribe before reading so changes during the read remain queued on the Redis connection.
        yield (
            b"data: " + await database_sync_to_async(_read_run_state, thread_sensitive=False)(team_id, run_id) + b"\n\n"
        )
        last_heartbeat = time.monotonic()
        while time.monotonic() - started_at < config.SSE_MAX_DURATION_SECONDS:
            message = await subscription.get_message(timeout=config.SSE_POLL_TIMEOUT_SECONDS)
            now = time.monotonic()
            if message and message.get("type") == "message":
                yield (
                    b"data: "
                    + await database_sync_to_async(_read_run_state, thread_sensitive=False)(team_id, run_id)
                    + b"\n\n"
                )
                last_heartbeat = now
            elif now - last_heartbeat >= config.SSE_HEARTBEAT_INTERVAL_SECONDS:
                yield b": ping\n\n"
                last_heartbeat = now
        yield b"event: end\ndata: reconnect\n\n"
