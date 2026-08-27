from datetime import timedelta
from uuid import UUID

from temporalio import activity, common, workflow

from posthog.temporal.common.base import PostHogWorkflow


@activity.defn(name="notebook-widget-generate")
def generate_widget_activity(job_id: str) -> None:
    from products.notebooks.backend.widgets import (  # noqa: PLC0415 — prevents a Temporal registry import cycle
        run_widget_generation_job,
    )

    run_widget_generation_job(UUID(job_id))


@activity.defn(name="notebook-widget-generate-mark-failed")
def mark_widget_generation_failed_activity(job_id: str) -> None:
    from products.notebooks.backend.widgets import (  # noqa: PLC0415 — prevents a Temporal registry import cycle
        fail_widget_generation_job,
    )

    fail_widget_generation_job(UUID(job_id))


@workflow.defn(name="notebook-widget-generate")
class NotebookWidgetGenerationWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> str:
        return inputs[0]

    @workflow.run
    async def run(self, job_id: str) -> None:
        try:
            await workflow.execute_activity(
                generate_widget_activity,
                job_id,
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=common.RetryPolicy(maximum_attempts=1),
            )
        except Exception:
            await workflow.execute_activity(
                mark_widget_generation_failed_activity,
                job_id,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=common.RetryPolicy(maximum_attempts=3),
            )
            raise
