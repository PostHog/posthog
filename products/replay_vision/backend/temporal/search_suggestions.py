"""Periodic batch refresh of the per-scanner search suggestions shown on the Search tab's empty state."""

import asyncio
from typing import TYPE_CHECKING

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from products.replay_vision.backend.temporal.constants import (
    LIST_STALE_SEARCH_SUGGESTIONS_TIMEOUT,
    REFRESH_SEARCH_SUGGESTIONS_TIMEOUT,
    SEARCH_SUGGESTIONS_CONCURRENCY,
    SEARCH_SUGGESTIONS_EXECUTION_TIMEOUT,
    SEARCH_SUGGESTIONS_MAX_PER_RUN,
    SEARCH_SUGGESTIONS_REFRESH_INTERVAL,
    SEARCH_SUGGESTIONS_SCHEDULE_ID,
    SEARCH_SUGGESTIONS_WORKFLOW_ID,
    SEARCH_SUGGESTIONS_WORKFLOW_NAME,
)
from products.replay_vision.backend.temporal.search_suggestions_types import (
    RefreshScannerSuggestionsInputs,
    RefreshSearchSuggestionsInputs,
    RefreshSearchSuggestionsResult,
)

if TYPE_CHECKING:
    from temporalio.client import Client

# `activities` pulls in Django, which the workflow sandbox can't safely re-import.
with workflow.unsafe.imports_passed_through():
    from products.replay_vision.backend.temporal.activities.refresh_search_suggestions import (
        list_stale_search_suggestions_activity,
        refresh_scanner_search_suggestions_activity,
    )


@workflow.defn(name=SEARCH_SUGGESTIONS_WORKFLOW_NAME)
class RefreshSearchSuggestionsWorkflow(PostHogWorkflow):
    inputs_cls = RefreshSearchSuggestionsInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: RefreshSearchSuggestionsInputs) -> RefreshSearchSuggestionsResult:
        stale = await workflow.execute_activity(
            list_stale_search_suggestions_activity,
            start_to_close_timeout=LIST_STALE_SEARCH_SUGGESTIONS_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if not stale:
            return RefreshSearchSuggestionsResult()

        # Each refresh is a model call, so bound the parallelism.
        semaphore = asyncio.Semaphore(SEARCH_SUGGESTIONS_CONCURRENCY)

        async def refresh(entry: RefreshScannerSuggestionsInputs) -> bool:
            async with semaphore:
                return await workflow.execute_activity(
                    refresh_scanner_search_suggestions_activity,
                    entry,
                    start_to_close_timeout=REFRESH_SEARCH_SUGGESTIONS_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

        outcomes = await asyncio.gather(*(refresh(entry) for entry in stale), return_exceptions=True)
        result = RefreshSearchSuggestionsResult(
            refreshed=[e.scanner_id for e, ok in zip(stale, outcomes) if ok is True],
            failed=[e.scanner_id for e, ok in zip(stale, outcomes) if ok is not True],
            # A full batch means candidates remain; the next hourly run picks them up.
            budget_exhausted=len(stale) >= SEARCH_SUGGESTIONS_MAX_PER_RUN,
        )
        if result.failed:
            workflow.logger.warning(
                "replay_vision.search_suggestions_partial_failure",
                extra={"failed": [str(s) for s in result.failed], "refreshed": len(result.refreshed)},
            )
        return result


async def create_replay_vision_search_suggestions_schedule(client: "Client") -> None:
    # Function-local: this module holds a `@workflow.defn`, so it must not re-import Django/temporalio.client
    # at module level for the workflow sandbox.
    from products.replay_vision.backend.temporal.schedule import upsert_interval_schedule  # noqa: PLC0415

    await upsert_interval_schedule(
        client,
        schedule_id=SEARCH_SUGGESTIONS_SCHEDULE_ID,
        workflow_name=SEARCH_SUGGESTIONS_WORKFLOW_NAME,
        workflow_id=SEARCH_SUGGESTIONS_WORKFLOW_ID,
        inputs=RefreshSearchSuggestionsInputs(),
        interval=SEARCH_SUGGESTIONS_REFRESH_INTERVAL,
        execution_timeout=SEARCH_SUGGESTIONS_EXECUTION_TIMEOUT,
    )
