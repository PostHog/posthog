"""Fire-and-forget starters for notebook Temporal workflows, callable from sync DRF views."""

from datetime import timedelta

from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.common.client import sync_connect

from products.notebooks.backend.temporal.frame_materialize import FrameMaterializeInputs
from products.notebooks.backend.temporal.sql_v2 import SQLV2RunInput
from products.notebooks.backend.temporal.widget_generation import WidgetGenerationInput


@async_to_sync
async def _start_workflow(
    temporal: Client,
    name: str,
    workflow_id: str,
    inputs: object,
    execution_timeout: timedelta | None = None,
) -> None:
    await temporal.start_workflow(
        name,
        inputs,
        id=workflow_id,
        task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        execution_timeout=execution_timeout,
    )


def start_sql_v2_run_workflow(inputs: SQLV2RunInput) -> None:
    _start_workflow(
        sync_connect(),
        "notebook-sandbox-cmd-run",
        f"notebook-sandbox-cmd-run-{inputs.run_id}",
        inputs,
    )


def start_frame_materialize_workflow(inputs: FrameMaterializeInputs) -> None:
    _start_workflow(
        sync_connect(),
        "notebook-frame-materialize",
        f"notebook-frame-materialize-{inputs.query_id}",
        inputs,
    )


def start_widget_generation_workflow(job_id: str, team_id: int) -> None:
    inputs = WidgetGenerationInput(job_id=job_id, team_id=team_id)
    try:
        _start_workflow(
            sync_connect(),
            "notebook-widget-generate",
            f"notebook-widget-generate-{job_id}",
            inputs,
            execution_timeout=timedelta(minutes=30),
        )
    except WorkflowAlreadyStartedError:
        pass
