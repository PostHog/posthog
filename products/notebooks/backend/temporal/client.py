"""Fire-and-forget starters for the DataV2 workflows, callable from sync DRF views."""

from uuid import uuid4

from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio.client import Client

from posthog.temporal.common.client import sync_connect

from products.notebooks.backend.temporal.data_v2 import DataV2RunInput, DataV2StartInput


@async_to_sync
async def _start_workflow(temporal: Client, name: str, workflow_id: str, inputs: object) -> None:
    await temporal.start_workflow(
        name,
        inputs,
        id=workflow_id,
        task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
    )


def start_data_v2_start_workflow(inputs: DataV2StartInput) -> None:
    _start_workflow(
        sync_connect(),
        "notebook-data-v2-start",
        f"notebook-data-v2-start-{inputs.notebook_short_id}-{uuid4()}",
        inputs,
    )


def start_data_v2_run_workflow(inputs: DataV2RunInput) -> None:
    _start_workflow(
        sync_connect(),
        "notebook-data-v2-run",
        f"notebook-data-v2-run-{inputs.run_id}",
        inputs,
    )
