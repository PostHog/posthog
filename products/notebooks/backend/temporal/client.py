"""Fire-and-forget starter for the SQLV2 run workflow, callable from sync DRF views."""

from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio.client import Client

from posthog.temporal.common.client import sync_connect

from products.notebooks.backend.temporal.sql_v2 import SQLV2RunInput


@async_to_sync
async def _start_workflow(temporal: Client, name: str, workflow_id: str, inputs: object) -> None:
    await temporal.start_workflow(
        name,
        inputs,
        id=workflow_id,
        task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
    )


def start_sql_v2_run_workflow(inputs: SQLV2RunInput) -> None:
    _start_workflow(
        sync_connect(),
        "notebook-sandbox-cmd-run",
        f"notebook-sandbox-cmd-run-{inputs.run_id}",
        inputs,
    )
