import pytest

from django.conf import settings

import pytest_asyncio
from temporalio.testing import ActivityEnvironment

from posthog.redis import get_async_client

from products.replay_vision.backend.temporal.gemini_cleanup_sweep.constants import REDIS_INDEX_KEY, REDIS_KEY_PREFIX


async def _drop_gemini_tracking_keys(client) -> None:
    keys = [k async for k in client.scan_iter(match=f"{REDIS_KEY_PREFIX}*")]
    if keys:
        await client.delete(*keys)
    await client.delete(REDIS_INDEX_KEY)


@pytest_asyncio.fixture
async def gemini_redis():
    """Async Vision Redis client with the gemini_cleanup_sweep namespace wiped before/after each test."""
    client = get_async_client(settings.REPLAY_VISION_REDIS_URL)
    await _drop_gemini_tracking_keys(client)
    yield client
    await _drop_gemini_tracking_keys(client)


@pytest.fixture
def activity_environment():
    """Return a testing temporal ActivityEnvironment."""
    return ActivityEnvironment()
