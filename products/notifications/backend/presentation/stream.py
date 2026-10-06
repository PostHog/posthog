import random
from collections.abc import AsyncGenerator
from uuid import UUID

from posthog.api.streaming import StreamBudget, sse_rotating_event_stream
from posthog.sync import database_sync_to_async

from products.notifications.backend.facade.api import can_receive_notifications, subscribe_to_notifications

SSE_MAX_DURATION_SECONDS = 15 * 60
# Tabs that connect together (for example, after a deploy) would otherwise rotate together every cycle.
SSE_MAX_DURATION_JITTER_SECONDS = 60.0

NOTIFICATIONS_STREAM_BUDGET = StreamBudget("NOTIFICATIONS_SSE_MAX_STREAMS_PER_PROCESS")


class _AccessRevokedError(Exception):
    pass


async def notification_event_stream(
    organization_id: UUID, user_id: int, *, domain_enforcement_exempt: bool
) -> AsyncGenerator[bytes]:
    max_duration = SSE_MAX_DURATION_SECONDS + random.uniform(0, SSE_MAX_DURATION_JITTER_SECONDS)
    still_allowed = database_sync_to_async(can_receive_notifications, thread_sensitive=False)
    async with subscribe_to_notifications(organization_id, user_id) as subscription:

        async def receive(timeout: float) -> bytes | None:
            payload = await subscription.receive(timeout)
            # The view checked access only when the stream opened. An admin can deactivate the user, remove
            # them, or turn on verified-domain enforcement while the stream is open.
            if payload is not None and not await still_allowed(
                user_id, organization_id, domain_enforcement_exempt=domain_enforcement_exempt
            ):
                raise _AccessRevokedError()
            return payload

        # The client refetches what it missed while it was disconnected when it reads `ready`, so send it only
        # after the subscription is live.
        yield b"event: ready\ndata: subscribed\n\n"
        try:
            async for chunk in sse_rotating_event_stream(receive, max_duration_seconds=max_duration):
                yield chunk
        except _AccessRevokedError:
            return
