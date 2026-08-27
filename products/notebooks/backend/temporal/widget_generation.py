from datetime import timedelta
from uuid import UUID

from temporalio import activity, common, workflow

from posthog.dataclasses import frozen
from posthog.temporal.common.base import PostHogWorkflow


@frozen
class WidgetGenerationInput:
    job_id: str
    team_id: int


@activity.defn(name="notebook-widget-generate")
def generate_widget_activity(inputs: WidgetGenerationInput) -> None:
    from products.notebooks.backend.widgets import (  # noqa: PLC0415 — prevents a Temporal registry import cycle
        run_widget_generation_job,
    )

    run_widget_generation_job(UUID(inputs.job_id), inputs.team_id)


@activity.defn(name="notebook-widget-generate-mark-failed")
def mark_widget_generation_failed_activity(inputs: WidgetGenerationInput) -> None:
    from products.notebooks.backend.widgets import (  # noqa: PLC0415 — prevents a Temporal registry import cycle
        fail_widget_generation_job,
    )

    fail_widget_generation_job(UUID(inputs.job_id), inputs.team_id)


@workflow.defn(name="notebook-widget-generate")
class NotebookWidgetGenerationWorkflow(PostHogWorkflow):
    inputs_cls = WidgetGenerationInput

    @workflow.run
    async def run(self, inputs: WidgetGenerationInput) -> None:
        try:
            await workflow.execute_activity(
                generate_widget_activity,
                inputs,
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=common.RetryPolicy(maximum_attempts=1),
            )
        except Exception:
            await workflow.execute_activity(
                mark_widget_generation_failed_activity,
                inputs,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=common.RetryPolicy(maximum_attempts=3),
            )
            raise
