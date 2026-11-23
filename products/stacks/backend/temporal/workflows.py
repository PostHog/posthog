"""Workflows for stack runs. Each runs one activity on the stacks queue, whose worker holds the engine."""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from products.stacks.backend.temporal.activities import clean_up_stacks, compute_stack_diff, push_stack_diff
    from products.stacks.backend.temporal.types import StackCleanupInput, StackRunInput

# Longer than the engine's own run timeout, so the engine always stops first and reports why.
RUN_TIMEOUT = timedelta(minutes=25)
# The push worker extends its lease and beats every 30 seconds. A worker that stops beating has died.
PUSH_HEARTBEAT_TIMEOUT = timedelta(minutes=2)


@workflow.defn(name="stacks-diff")
class StackDiffWorkflow(PostHogWorkflow):
    inputs_cls = StackRunInput

    @workflow.run
    async def run(self, input: StackRunInput) -> None:
        # A diff only reads, so a retry after a lost worker is safe. The activity marks the diff failed
        # on any error it can see, so a retry happens only when the worker itself went away.
        await workflow.execute_activity(
            compute_stack_diff,
            input,
            start_to_close_timeout=RUN_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=2),
        )


@workflow.defn(name="stacks-push")
class StackPushWorkflow(PostHogWorkflow):
    inputs_cls = StackRunInput

    @workflow.run
    async def run(self, input: StackRunInput) -> None:
        # A push writes entities, so it never runs twice by itself. A push whose worker died keeps its lease
        # until the lease expires. The cleanup schedule then marks it uncertain.
        await workflow.execute_activity(
            push_stack_diff,
            input,
            start_to_close_timeout=RUN_TIMEOUT,
            heartbeat_timeout=PUSH_HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


@workflow.defn(name="stacks-cleanup")
class StackCleanupWorkflow(PostHogWorkflow):
    inputs_cls = StackCleanupInput
    inputs_optional = True

    @workflow.run
    async def run(self, input: StackCleanupInput) -> None:
        await workflow.execute_activity(
            clean_up_stacks,
            input,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
