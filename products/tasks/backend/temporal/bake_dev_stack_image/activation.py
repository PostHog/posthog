import uuid
import asyncio
from datetime import timedelta
from threading import Event

from asgiref.sync import sync_to_async
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.utils import close_db_connections, retry_on_db_connection_drop

from products.tasks.backend.dev_stack_image_models import DevStackImageAttempt
from products.tasks.backend.logic.services.dev_stack_image import bake_dev_stack_image
from products.tasks.backend.logic.services.dev_stack_image_state import DevStackImageState
from products.tasks.backend.logic.services.dev_stack_image_verification import (
    DevStackImageVerificationError,
    verify_dev_stack_image,
)
from products.tasks.backend.metrics import observe_dev_stack_image_bake


async def renew_lease(state: DevStackImageState, attempt_id: uuid.UUID, owner: uuid.UUID) -> None:
    while True:
        activity.heartbeat()
        await asyncio.sleep(30)
        if not await sync_to_async(retry_on_db_connection_drop)(lambda: state.renew(attempt_id, owner)):
            raise RuntimeError("Dev-stack bake no longer owns its generation")


async def build_and_activate(
    state: DevStackImageState, attempt: DevStackImageAttempt, owner: uuid.UUID, cancelled: Event
) -> str:
    image_id = attempt.candidate_image_id or await sync_to_async(bake_dev_stack_image, thread_sensitive=False)(
        candidate=attempt, cancelled=cancelled
    )
    if not await sync_to_async(retry_on_db_connection_drop)(lambda: state.checkpoint(attempt.id, owner, image_id)):
        return "superseded"
    version = await sync_to_async(verify_dev_stack_image, thread_sensitive=False)(attempt, image_id)
    if not await sync_to_async(retry_on_db_connection_drop)(
        lambda: state.activate(attempt.id, owner, image_id, version)
    ):
        return "superseded"
    observe_dev_stack_image_bake("succeeded", trigger="protected")
    return image_id


@activity.defn
@close_db_connections
async def activate_dev_stack_image(attempt_id: str) -> str:
    attempt = await sync_to_async(retry_on_db_connection_drop)(
        lambda: DevStackImageAttempt.objects.using("default").get(pk=attempt_id)
    )
    state = DevStackImageState(attempt.target_id)
    owner = uuid.uuid4()
    run_id = activity.info().workflow_run_id or ""
    claimed = await sync_to_async(retry_on_db_connection_drop)(lambda: state.claim(attempt.id, owner, run_id))
    if claimed is None:
        return "not_claimed"
    lease = asyncio.create_task(renew_lease(state, attempt.id, owner))
    cancelled = Event()
    build = asyncio.create_task(build_and_activate(state, claimed, owner, cancelled))
    try:
        done, _ = await asyncio.wait([lease, build], return_when=asyncio.FIRST_COMPLETED)
        if lease in done:
            await lease
        return await build
    except BaseException as error:
        observe_dev_stack_image_bake("failed", trigger="protected")
        invalid = isinstance(error, DevStackImageVerificationError)
        await asyncio.shield(
            sync_to_async(retry_on_db_connection_drop)(lambda: state.fail(attempt.id, owner, invalid=invalid))
        )
        raise
    finally:
        cancelled.set()
        for task in (lease, build):
            task.cancel()
        await asyncio.gather(lease, build, return_exceptions=True)


@workflow.defn(name="activate-dev-stack-image")
class ActivateDevStackImageWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> str:
        return str(uuid.UUID(inputs[0]))

    @workflow.run
    async def run(self, attempt_id: str) -> str:
        return await workflow.execute_activity(
            activate_dev_stack_image,
            attempt_id,
            start_to_close_timeout=timedelta(hours=3),
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
