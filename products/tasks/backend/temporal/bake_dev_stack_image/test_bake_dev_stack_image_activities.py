import threading
import dataclasses
from datetime import timedelta

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
    # The heartbeat interval is derived from this timeout, and the default is None (no
    # heartbeating at all), so a short real timeout is what makes the loop tick here.
    env.info = dataclasses.replace(env.info, heartbeat_timeout=timedelta(seconds=0.06))
    heartbeat_seen = threading.Event()
    env.on_heartbeat = lambda *details: heartbeat_seen.set()

    # Recorded from inside the bake so the assertion can't be satisfied by the single
    # heartbeat the context manager emits on exit.
    heartbeat_during_bake: list[bool] = []

    def blocking_bake(publish_name: str) -> str:
        heartbeat_during_bake.append(heartbeat_seen.wait(timeout=10))
        return "im-1"

    with patch(
        "products.tasks.backend.temporal.bake_dev_stack_image.activities.bake_dev_stack_image",
        side_effect=blocking_bake,
    ):
        result = await env.run(
            bake_and_publish_dev_stack_image, BakeDevStackImageInput(publish_name="posthog-dev-stack")
        )

    assert result == "im-1"
    assert heartbeat_during_bake == [True]
