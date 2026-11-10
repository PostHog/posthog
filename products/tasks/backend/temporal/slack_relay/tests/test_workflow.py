import uuid

import pytest

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.slack_app.backend.facade.temporal import (
    PresentSlackReplyInput,
    SlackReplyPresentation,
    SlackReplyPresentationGateInput,
)
from products.tasks.backend.temporal.slack_relay.activities import RelaySlackMessageInput
from products.tasks.backend.temporal.slack_relay.workflow import PostHogCodeAgentRelayWorkflow

pytestmark = [pytest.mark.asyncio]


class TestPostHogCodeAgentRelayWorkflow:
    @pytest.mark.parametrize(
        "delivered,offer_presentation,enabled,presented",
        [
            pytest.param(True, True, True, True, id="delivered_answer"),
            pytest.param(False, True, True, False, id="answer_not_delivered"),
            pytest.param(True, False, True, False, id="not_the_agents_answer"),
            pytest.param(True, True, False, False, id="flag_off"),
        ],
    )
    @pytest.mark.timeout(60, func_only=True)
    async def test_only_a_delivered_agent_answer_gets_a_presentation(
        self, delivered: bool, offer_presentation: bool, enabled: bool, presented: bool
    ) -> None:
        presentations: list[PresentSlackReplyInput] = []

        @activity.defn(name="relay_slack_message")
        async def relay(input: RelaySlackMessageInput) -> bool:
            return delivered

        @activity.defn(name="is_slack_reply_presentation_enabled_activity")
        async def gate(input: SlackReplyPresentationGateInput) -> bool:
            return enabled

        @activity.defn(name="present_slack_reply_activity")
        async def present(input: PresentSlackReplyInput) -> SlackReplyPresentation:
            presentations.append(input)
            return SlackReplyPresentation(components=1)

        async with await WorkflowEnvironment.start_time_skipping() as env:
            task_queue = f"test-{uuid.uuid4()}"
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[PostHogCodeAgentRelayWorkflow],
                activities=[relay, gate, present],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                await env.client.execute_workflow(
                    PostHogCodeAgentRelayWorkflow.run,
                    RelaySlackMessageInput(
                        run_id="run-1",
                        relay_id="relay-1",
                        text="Signups grew.",
                        trace_id="trace-1",
                        offer_presentation=offer_presentation,
                    ),
                    id=f"relay-{uuid.uuid4()}",
                    task_queue=task_queue,
                )

        assert [(p.run_id, p.answer_markdown, p.trace_id, p.stream_ts) for p in presentations] == (
            [("run-1", "Signups grew.", "trace-1", None)] if presented else []
        )
