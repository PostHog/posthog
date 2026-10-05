import random
from collections.abc import AsyncGenerator
from uuid import UUID

from posthog.api.streaming import StreamBudget, sse_rotating_event_stream

from products.notifications.backend.facade.api import subscribe_to_notifications

SSE_MAX_DURATION_SECONDS = 15 * 60
# Tabs that connect together (for example, after a deploy) would otherwise rotate together every cycle.
SSE_MAX_DURATION_JITTER_SECONDS = 60.0

NOTIFICATIONS_STREAM_BUDGET = StreamBudget("NOTIFICATIONS_SSE_MAX_STREAMS_PER_PROCESS")


async def notification_event_stream(organization_id: UUID, user_id: int) -> AsyncGenerator[bytes]:
    max_duration = SSE_MAX_DURATION_SECONDS + random.uniform(0, SSE_MAX_DURATION_JITTER_SECONDS)
    async with subscribe_to_notifications(organization_id, user_id) as subscription:
        # The client refetches what it missed while it was disconnected when it reads `ready`, so send it only
        # after the subscription is live.
        yield b"event: ready\ndata: subscribed\n\n"
        async for chunk in sse_rotating_event_stream(subscription.receive, max_duration_seconds=max_duration):
            yield chunk
