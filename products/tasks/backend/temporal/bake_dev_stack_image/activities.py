import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Literal

from asgiref.sync import sync_to_async
from temporalio import activity

from products.tasks.backend.logic.services.dev_stack_image import (
    DEV_STACK_IMAGE_NAME,
    DevStackImageBakeError,
    bake_dev_stack_image,
)
from products.tasks.backend.metrics import observe_dev_stack_image_bake
from products.tasks.backend.temporal.observability import log_activity_execution

logger = logging.getLogger(__name__)

BAKE_HEARTBEAT_INTERVAL_SECONDS = 30


@dataclass
class BakeDevStackImageInput:
    publish_name: str = DEV_STACK_IMAGE_NAME
    trigger: Literal["nightly", "base_changed", "manual"] = "manual"

    def to_log_context(self) -> dict[str, Any]:
        return {"publish_name": self.publish_name, "trigger": self.trigger}


@activity.defn
async def bake_and_publish_dev_stack_image(input: BakeDevStackImageInput) -> str:
    """Run the bake and publish the snapshot under the input's Modal image name.

    Heartbeats while the sync bake blocks so worker failures are detected within the
    workflow's heartbeat timeout.
    """
    stop_heartbeat = asyncio.Event()

    async def _heartbeat_loop() -> None:
        while True:
            try:
                await asyncio.wait_for(stop_heartbeat.wait(), timeout=BAKE_HEARTBEAT_INTERVAL_SECONDS)
                return
            except TimeoutError:
                activity.heartbeat()

    heartbeat_task = asyncio.create_task(_heartbeat_loop())
    try:
        with log_activity_execution("bake_and_publish_dev_stack_image", **input.to_log_context()):
            try:
                image_id = await sync_to_async(bake_dev_stack_image, thread_sensitive=False)(input.publish_name)
            except DevStackImageBakeError:
                observe_dev_stack_image_bake("bake_failed", trigger=input.trigger)
                raise
            except Exception:
                observe_dev_stack_image_bake("failed", trigger=input.trigger)
                raise
            observe_dev_stack_image_bake("succeeded", trigger=input.trigger)
            return image_id
    finally:
        stop_heartbeat.set()
        await heartbeat_task
