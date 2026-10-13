import uuid
from dataclasses import dataclass, field

import pytest

from parameterized import parameterized
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.schedule import schedules

from products.metrics.backend.facade.temporal import create_suggested_dashboards_discovery_schedule
from products.metrics.backend.temporal.inputs import FinishInputs, GenerateInputs, GenerationRequestInputs, RoundInputs
from products.metrics.backend.temporal.workflows import MetricsDashboardGenerateWorkflow


@dataclass(frozen=False)
class Script:
    started: bool = True
    draft_fails: bool = False
    verdicts: list[bool] = field(default_factory=list)
    render_fails: bool = False
    calls: list[str] = field(default_factory=list)
    finish_error: str | None = "not called"


async def _run(script: Script) -> str | None:
    @activity.defn(name="start_generation_activity")
    async def start(inputs: GenerateInputs) -> str | None:
        return "template-1" if script.started else None

    @activity.defn(name="draft_template_activity")
    async def draft(template_id: str) -> int:
        if script.draft_fails:
            raise ApplicationError("The model call failed", non_retryable=True)
        return 6

    @activity.defn(name="render_preview_activity")
    async def render(inputs: RoundInputs) -> int | None:
        script.calls.append(f"render {inputs.round}")
        if script.render_fails:
            raise ApplicationError("No picture", non_retryable=True)
        return inputs.round

    @activity.defn(name="check_preview_activity")
    async def check(inputs: RoundInputs) -> bool:
        script.calls.append(f"check {inputs.round} revise={inputs.revise}")
        return script.verdicts[inputs.round - 1]

    @activity.defn(name="finish_generation_activity")
    async def finish(inputs: FinishInputs) -> None:
        script.finish_error = inputs.error

    async with await WorkflowEnvironment.start_time_skipping() as env:
        task_queue = f"test-{uuid.uuid4()}"
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[MetricsDashboardGenerateWorkflow],
            activities=[start, draft, render, check, finish],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            return await env.client.execute_workflow(
                MetricsDashboardGenerateWorkflow.run,
                GenerateInputs(
                    team_id=1,
                    request=GenerationRequestInputs(key="k", name="Queue", description="", metric_names=["a"]),
                ),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )


@pytest.mark.asyncio
@parameterized.expand(
    [
        (
            "stops_when_a_round_passes",
            Script(verdicts=[False, True]),
            ["render 1", "check 1 revise=True", "render 2", "check 2 revise=True"],
            None,
        ),
        (
            "last_round_only_records_a_verdict",
            Script(verdicts=[False, False, False]),
            [
                "render 1",
                "check 1 revise=True",
                "render 2",
                "check 2 revise=True",
                "render 3",
                "check 3 revise=False",
            ],
            None,
        ),
        ("a_failed_render_ends_the_checks", Script(render_fails=True), ["render 1"], None),
        ("a_failed_draft_fails_the_template", Script(draft_fails=True), [], "The model call failed"),
    ]
)
async def test_generation_rounds(_name: str, script: Script, calls: list[str], finish_error: str | None) -> None:
    template_id = await _run(script)

    assert template_id == "template-1"
    assert script.calls == calls
    assert script.finish_error == finish_error


@pytest.mark.asyncio
async def test_generation_skips_metrics_that_the_bank_already_holds() -> None:
    script = Script(started=False)

    assert await _run(script) is None
    assert script.calls == []
    assert script.finish_error == "not called"


def test_discovery_schedule_is_registered() -> None:
    assert create_suggested_dashboards_discovery_schedule in schedules
