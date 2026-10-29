import asyncio

from django.conf import settings

from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.common.client import async_connect

from ..adapters.command_tag import command_dedupe_id
from .merge_workflow import MergeCheckInputs, MergeCheckWorkflow

START_TIMEOUT_SECONDS = 2


def merge_check_workflow_id(inputs: MergeCheckInputs) -> str:
    if inputs.command is not None:
        return command_dedupe_id(inputs.repository, inputs.command.pull_request_number)
    return f"knowledge_writer:repo_merge:{inputs.commit_sha}"


def start_merge_check(inputs: MergeCheckInputs) -> bool:
    return asyncio.run(asyncio.wait_for(start_merge_check_workflow(inputs), START_TIMEOUT_SECONDS))


async def start_merge_check_workflow(inputs: MergeCheckInputs) -> bool:
    client = await async_connect()
    try:
        await client.start_workflow(
            MergeCheckWorkflow.run,
            inputs,
            id=merge_check_workflow_id(inputs),
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        )
    except WorkflowAlreadyStartedError:
        return False
    return True
