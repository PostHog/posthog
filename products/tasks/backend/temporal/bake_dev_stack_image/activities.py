import logging
from dataclasses import dataclass
from typing import Any

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.logic.services.dev_stack_image import DEV_STACK_IMAGE_NAME, bake_dev_stack_image
from products.tasks.backend.metrics import observe_dev_stack_image_bake
from products.tasks.backend.temporal.observability import log_activity_execution

logger = logging.getLogger(__name__)


@dataclass
class BakeDevStackImageActivityInput:
    publish_name: str = DEV_STACK_IMAGE_NAME

    def to_log_context(self) -> dict[str, Any]:
        return {"publish_name": self.publish_name}


@activity.defn
@asyncify
def bake_and_publish_dev_stack_image(input: BakeDevStackImageActivityInput) -> str:
    with log_activity_execution("bake_and_publish_dev_stack_image", **input.to_log_context()):
        try:
            return bake_dev_stack_image(input.publish_name)
        except Exception:
            observe_dev_stack_image_bake("failed")
            raise
