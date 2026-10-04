"""Periodic distillation of observation ratings into the hidden rules scans include."""

import asyncio
from typing import TYPE_CHECKING

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from products.replay_vision.backend.temporal.constants import (
    LEARNED_RULES_CONCURRENCY,
    LEARNED_RULES_EXECUTION_TIMEOUT,
    LEARNED_RULES_REFRESH_INTERVAL,
    LEARNED_RULES_SCHEDULE_ID,
    LEARNED_RULES_WORKFLOW_ID,
    LEARNED_RULES_WORKFLOW_NAME,
    LIST_DUE_LEARNED_RULES_TIMEOUT,
    REFRESH_TEAM_LEARNED_RULES_TIMEOUT,
)
from products.replay_vision.backend.temporal.learned_rules_types import (
    RefreshLearnedRulesInputs,
    RefreshLearnedRulesResult,
    RefreshTeamLearnedRulesInputs,
)

if TYPE_CHECKING:
    from temporalio.client import Client

# `activities` pulls in Django, which the workflow sandbox can't safely re-import.
with workflow.unsafe.imports_passed_through():
    from products.replay_vision.backend.temporal.activities.refresh_learned_rules import (
        list_due_learned_rules_teams_activity,
        refresh_team_learned_rules_activity,
    )


@workflow.defn(name=LEARNED_RULES_WORKFLOW_NAME)
class RefreshLearnedRulesWorkflow(PostHogWorkflow):
    inputs_cls = RefreshLearnedRulesInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: RefreshLearnedRulesInputs) -> RefreshLearnedRulesResult:
        due = await workflow.execute_activity(
            list_due_learned_rules_teams_activity,
            start_to_close_timeout=LIST_DUE_LEARNED_RULES_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if not due:
            return RefreshLearnedRulesResult()

        # Each refresh is a model call, so bound the parallelism.
        semaphore = asyncio.Semaphore(LEARNED_RULES_CONCURRENCY)

        async def refresh(entry: RefreshTeamLearnedRulesInputs) -> bool:
            async with semaphore:
                return await workflow.execute_activity(
                    refresh_team_learned_rules_activity,
                    entry,
                    start_to_close_timeout=REFRESH_TEAM_LEARNED_RULES_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

        outcomes = await asyncio.gather(*(refresh(entry) for entry in due), return_exceptions=True)
        result = RefreshLearnedRulesResult(
            refreshed=[e.team_id for e, ok in zip(due, outcomes) if ok is True],
            skipped=[e.team_id for e, ok in zip(due, outcomes) if ok is False],
            failed=[e.team_id for e, ok in zip(due, outcomes) if isinstance(ok, BaseException)],
        )
        if result.failed:
            workflow.logger.warning(
                "replay_vision.learned_rules_partial_failure",
                extra={"failed": result.failed, "refreshed": len(result.refreshed)},
            )
        return result


async def create_replay_vision_learned_rules_schedule(client: "Client") -> None:
    # Function-local: this module holds a `@workflow.defn`, so it must not re-import Django/temporalio.client
    # at module level for the workflow sandbox.
    from posthog.scheduling.jitter import deterministic_offset  # noqa: PLC0415

    from products.replay_vision.backend.temporal.schedule import upsert_interval_schedule  # noqa: PLC0415

    await upsert_interval_schedule(
        client,
        schedule_id=LEARNED_RULES_SCHEDULE_ID,
        workflow_name=LEARNED_RULES_WORKFLOW_NAME,
        workflow_id=LEARNED_RULES_WORKFLOW_ID,
        inputs=RefreshLearnedRulesInputs(),
        interval=LEARNED_RULES_REFRESH_INTERVAL,
        offset=deterministic_offset(LEARNED_RULES_SCHEDULE_ID, LEARNED_RULES_REFRESH_INTERVAL),
        execution_timeout=LEARNED_RULES_EXECUTION_TIMEOUT,
    )
