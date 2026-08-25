import time

import pytest
from unittest.mock import patch

from temporalio.testing import ActivityEnvironment

from products.tasks.backend.temporal.bake_dev_stack_image.activities import (
    BakeDevStackImageInput,
    bake_and_publish_dev_stack_image,
)


@pytest.mark.asyncio
async def test_bake_activity_heartbeats_while_the_sync_bake_blocks() -> None:
    # Without heartbeats, a worker crash mid-bake goes undetected until the 3-hour
    # start_to_close (~6h across both attempts) instead of the heartbeat timeout.
    env = ActivityEnvironment()
    heartbeats: list[tuple] = []
    env.on_heartbeat = lambda *details: heartbeats.append(details)

    def slow_bake(publish_name: str) -> str:
        time.sleep(0.3)
        return "im-1"

    with (
        patch("products.tasks.backend.temporal.bake_dev_stack_image.activities.BAKE_HEARTBEAT_INTERVAL_SECONDS", 0.01),
        patch(
            "products.tasks.backend.temporal.bake_dev_stack_image.activities.bake_dev_stack_image",
            side_effect=slow_bake,
        ),
    ):
        result = await env.run(
            bake_and_publish_dev_stack_image, BakeDevStackImageInput(publish_name="posthog-dev-stack")
        )

    assert result == "im-1"
    assert heartbeats
