from datetime import timedelta
from uuid import UUID

from temporalio import activity, common, workflow
from temporalio.exceptions import ActivityError, ApplicationError

from posthog.dataclasses import frozen
from posthog.temporal.common.base import PostHogWorkflow


@frozen
class WidgetGenerationInput:
    job_id: str
    team_id: int


GENERATION_CAPACITY_ERROR_TYPE = "notebook_widget_generation_capacity"
GENERATION_CAPACITY_RETRY_ATTEMPTS = 20


@activity.defn(name="notebook-widget-generate")
def generate_widget_activity(inputs: WidgetGenerationInput) -> None:
    from posthog.clickhouse.client.limit import (  # noqa: PLC0415 — keeps Redis limiter setup out of workflow imports
        ConcurrencyLimitExceeded,
    )

    from products.notebooks.backend.widget_generation_capacity import (  # noqa: PLC0415 — keeps Redis setup activity-only
        widget_generation_slot,
    )
    from products.notebooks.backend.widgets import (  # noqa: PLC0415 — prevents a Temporal registry import cycle
        heartbeat_widget_generation_job,
        run_widget_generation_job,
    )

    heartbeat_widget_generation_job(UUID(inputs.job_id), inputs.team_id)
    try:
        with widget_generation_slot(team_id=inputs.team_id, job_id=inputs.job_id):
            run_widget_generation_job(UUID(inputs.job_id), inputs.team_id)
    except ConcurrencyLimitExceeded as error:
        raise ApplicationError(
            "Widget generation capacity is full.",
            type=GENERATION_CAPACITY_ERROR_TYPE,
            non_retryable=True,
        ) from error


@activity.defn(name="notebook-widget-generate-mark-failed")
def mark_widget_generation_failed_activity(inputs: WidgetGenerationInput) -> None:
    from products.notebooks.backend.widgets import (  # noqa: PLC0415 — prevents a Temporal registry import cycle
        fail_widget_generation_job,
    )

    fail_widget_generation_job(UUID(inputs.job_id), inputs.team_id)


@activity.defn(name="notebook-widget-generate-mark-capacity-failed")
def mark_widget_generation_capacity_failed_activity(inputs: WidgetGenerationInput) -> None:
    from products.notebooks.backend.widgets import (  # noqa: PLC0415 — prevents a Temporal registry import cycle
        fail_widget_generation_capacity_job,
    )

    fail_widget_generation_capacity_job(UUID(inputs.job_id), inputs.team_id)


@workflow.defn(name="notebook-widget-generate")
class NotebookWidgetGenerationWorkflow(PostHogWorkflow):
    inputs_cls = WidgetGenerationInput

    @workflow.run
    async def run(self, inputs: WidgetGenerationInput) -> None:
        failure_activity = mark_widget_generation_failed_activity
        try:
            for attempt in range(GENERATION_CAPACITY_RETRY_ATTEMPTS):
                try:
                    await workflow.execute_activity(
                        generate_widget_activity,
                        inputs,
                        start_to_close_timeout=timedelta(minutes=15),
                        retry_policy=common.RetryPolicy(maximum_attempts=1),
                    )
                    return
                except ActivityError as error:
                    capacity_full = isinstance(error.cause, ApplicationError) and (
                        error.cause.type == GENERATION_CAPACITY_ERROR_TYPE
                    )
                    if not capacity_full or attempt == GENERATION_CAPACITY_RETRY_ATTEMPTS - 1:
                        if capacity_full:
                            failure_activity = mark_widget_generation_capacity_failed_activity
                        raise
                    await workflow.sleep(timedelta(seconds=30))
        except Exception:
            await workflow.execute_activity(
                failure_activity,
                inputs,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=common.RetryPolicy(maximum_attempts=3),
            )
            raise
