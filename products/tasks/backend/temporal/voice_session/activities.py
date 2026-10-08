import json
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.utils import timezone

import aiohttp
from temporalio import activity

from posthog.dataclasses import frozen
from posthog.egress.openai_live.transport import attach_live_session
from posthog.temporal.common.logger import get_logger

from products.tasks.backend.logic.services.voice_session_monitor import (
    LiveSessionDisconnected,
    VoiceSessionOutcome,
    VoiceSessionProgress,
    monitor_live_session,
)
from products.tasks.backend.logic.services.voice_sessions import (
    VoiceSessionRecord,
    capture_delegated_response,
    capture_voice_session_ended,
)

logger = get_logger(__name__)

MONITOR_MAX_ATTEMPTS = 4


@frozen
class VoiceSessionMonitorInput:
    record: VoiceSessionRecord
    started_at: str
    max_duration_seconds: int


class _AiohttpLiveConnection:
    def __init__(self, connection: aiohttp.ClientWebSocketResponse) -> None:
        self._connection = connection

    async def send(self, event: dict[str, Any]) -> None:
        await self._connection.send_json(event)

    async def receive(self, timeout: float) -> dict[str, Any] | None:
        try:
            message = await self._connection.receive(timeout=timeout)
        except TimeoutError:
            return None
        if message.type in (
            aiohttp.WSMsgType.CLOSE,
            aiohttp.WSMsgType.CLOSING,
            aiohttp.WSMsgType.CLOSED,
            aiohttp.WSMsgType.ERROR,
        ):
            raise LiveSessionDisconnected
        if message.type != aiohttp.WSMsgType.TEXT:
            return None
        try:
            event = json.loads(message.data)
        except ValueError:
            return None
        return event if isinstance(event, dict) else None


@activity.defn
async def monitor_voice_session(input: VoiceSessionMonitorInput) -> None:
    details = activity.info().heartbeat_details
    # A retry resumes from the last usage snapshot, so a worker restart does not lose the duration.
    progress = VoiceSessionProgress(seconds=details[0] if details and isinstance(details[0], int) else None)
    deadline = datetime.fromisoformat(input.started_at) + timedelta(seconds=input.max_duration_seconds)
    try:
        outcome = await _follow_session(input, progress, deadline)
    except Exception:
        if activity.info().attempt < MONITOR_MAX_ATTEMPTS:
            raise
        logger.exception("desktop_voice_monitor_failed", voice_session_id=input.record.session_id)
        outcome = progress.outcome("monitor_failed")
    capture_voice_session_ended(input.record, outcome)


async def _follow_session(
    input: VoiceSessionMonitorInput, progress: VoiceSessionProgress, deadline: datetime
) -> VoiceSessionOutcome:
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=None, sock_connect=10), trust_env=True
    ) as http:
        try:
            connection = await attach_live_session(http, settings.OPENAI_LIVE_API_KEY, input.record.session_id)
        except aiohttp.WSServerHandshakeError as error:
            if 400 <= error.status < 500 and error.status not in (408, 429):
                logger.warning(
                    "desktop_voice_monitor_attach_rejected",
                    voice_session_id=input.record.session_id,
                    status_code=error.status,
                )
                return progress.outcome("unavailable")
            raise
        async with connection:
            return await monitor_live_session(
                _AiohttpLiveConnection(connection),
                progress,
                deadline=deadline,
                now=timezone.now,
                heartbeat=activity.heartbeat,
                on_response_usage=lambda usage: capture_delegated_response(input.record, usage),
            )
