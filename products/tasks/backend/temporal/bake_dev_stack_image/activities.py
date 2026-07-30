import logging
import threading
import contextvars
from dataclasses import dataclass
from typing import Any

from temporalio import activity

from posthog.temporal.common.utils import asyncify

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

    def to_log_context(self) -> dict[str, Any]:
        return {"publish_name": self.publish_name}


@activity.defn
@asyncify
def bake_and_publish_dev_stack_image(input: BakeDevStackImageInput) -> str:
    """Run the bake and publish the snapshot under the input's Modal image name.

    Heartbeats from a side thread while the sync bake blocks (15-90 minutes), so a
    worker crash or redeploy mid-bake is detected within the workflow's heartbeat
    timeout and retried promptly, instead of burning the full 3-hour start_to_close
    (mirrors send_followup_to_sandbox).
    """
    stop_heartbeat = threading.Event()
    heartbeat_ctx = contextvars.copy_context()

    def _heartbeat_loop() -> None:
        while not stop_heartbeat.wait(BAKE_HEARTBEAT_INTERVAL_SECONDS):
            try:
                activity.heartbeat()
            except Exception:
                return

    heartbeat_thread = threading.Thread(target=lambda: heartbeat_ctx.run(_heartbeat_loop), daemon=True)
    heartbeat_thread.start()
    try:
        with log_activity_execution("bake_and_publish_dev_stack_image", **input.to_log_context()):
            try:
                image_id = bake_dev_stack_image(input.publish_name)
            except DevStackImageBakeError:
                observe_dev_stack_image_bake("bake_failed")
                raise
            except Exception:
                observe_dev_stack_image_bake("failed")
                raise
            observe_dev_stack_image_bake("succeeded")
            return image_id
    finally:
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=2)
