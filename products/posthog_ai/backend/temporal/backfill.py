"""Backfill loop: walk every LangGraph conversation that has no task and copy it into one.

The conversation table is the progress table: a copied conversation gets a task, so "not done" is
"no task". The loop carries only a cursor and counters, and continues as new after every page so
history never grows. A restart from the top is correct, just slower; pass `start_after` to resume
from the last cursor the loop logged.
"""

import asyncio
from dataclasses import replace
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import is_cancelled_exception

from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow

from products.posthog_ai.backend.models.assistant import Conversation
from products.posthog_ai.backend.temporal.activities import (
    MirrorActivityResult,
    MirrorConversationInputs,
    mirror_conversation_to_task_activity,
)

BACKFILL_WORKFLOW_NAME = "backfill-conversation-tasks"

LIST_ACTIVITY_TIMEOUT = timedelta(seconds=60)
COPY_ACTIVITY_TIMEOUT = timedelta(minutes=5)
ACTIVITY_RETRY_POLICY = RetryPolicy(maximum_attempts=3)
# One page of ids crosses the activity boundary as a Temporal payload, and each copy adds a
# handful of history events, so the page also bounds the history of one run.
MIN_BATCH_SIZE = 1
MAX_BATCH_SIZE = 2000
MIN_CONCURRENCY = 1
MAX_CONCURRENCY = 200
FLAG_OFF_REASON = "flag"


@frozen
class ConversationBackfillInputs:
    start_after: str | None = None
    batch_size: int = 500
    concurrency: int = 16
    dry_run: bool = False
    pause_seconds: float = 0.0
    seen: int = 0
    copied: int = 0
    skipped: int = 0
    failed: int = 0


@frozen
class BackfillCandidate:
    conversation_id: str
    team_id: int
    user_id: int


@frozen
class ListCandidatesInputs:
    start_after: str | None
    limit: int


@frozen
class ListCandidatesOutput:
    candidates: list[BackfillCandidate]
    next_cursor: str | None
    exhausted: bool


@frozen
class ConversationBackfillSummary:
    seen: int
    copied: int
    skipped: int
    failed: int
    last_cursor: str | None
    # "exhausted" when the walk reached the end, "kill_switch" when every copy in a page was
    # refused by the flag.
    stopped_because: str


def list_candidates(inputs: ListCandidatesInputs) -> ListCandidatesOutput:
    queryset = Conversation.objects.filter(
        agent_runtime=Conversation.AgentRuntime.LANGGRAPH,
        type=Conversation.Type.ASSISTANT,
        task_id__isnull=True,
        deleted=False,
        is_internal=False,
    )
    if inputs.start_after is not None:
        queryset = queryset.filter(id__gt=inputs.start_after)
    # The primary key index already orders the walk; ordering by anything else sorts every
    # remaining row on each page.
    rows = list(queryset.order_by("id").values_list("id", "team_id", "user_id")[: inputs.limit])
    candidates = [
        BackfillCandidate(conversation_id=str(conversation_id), team_id=team_id, user_id=user_id)
        for conversation_id, team_id, user_id in rows
    ]
    next_cursor = candidates[-1].conversation_id if candidates else inputs.start_after
    return ListCandidatesOutput(candidates=candidates, next_cursor=next_cursor, exhausted=len(rows) < inputs.limit)


@activity.defn
async def list_conversations_to_backfill_activity(inputs: ListCandidatesInputs) -> ListCandidatesOutput:
    return await database_sync_to_async(list_candidates, thread_sensitive=False)(inputs)


@workflow.defn(name=BACKFILL_WORKFLOW_NAME)
class ConversationBackfillWorkflow(PostHogWorkflow):
    inputs_cls = ConversationBackfillInputs

    @workflow.run
    async def run(self, inputs: ConversationBackfillInputs) -> ConversationBackfillSummary:
        batch_size = min(max(inputs.batch_size, MIN_BATCH_SIZE), MAX_BATCH_SIZE)
        concurrency = min(max(inputs.concurrency, MIN_CONCURRENCY), MAX_CONCURRENCY)

        page = await workflow.execute_activity(
            list_conversations_to_backfill_activity,
            ListCandidatesInputs(start_after=inputs.start_after, limit=batch_size),
            start_to_close_timeout=LIST_ACTIVITY_TIMEOUT,
            retry_policy=ACTIVITY_RETRY_POLICY,
        )

        copied = skipped = failed = 0
        flag_off = 0
        if page.candidates and not inputs.dry_run:
            results = await self._copy_page(page.candidates, concurrency)
            for candidate, result in zip(page.candidates, results):
                if isinstance(result, BaseException):
                    if is_cancelled_exception(result):
                        raise result
                    failed += 1
                    workflow.logger.warning(
                        "conversation_backfill.copy_failed",
                        extra={"conversation_id": candidate.conversation_id, "error": str(result)[:500]},
                    )
                elif result.skipped_reason is None:
                    copied += 1
                else:
                    skipped += 1
                    flag_off += result.skipped_reason == FLAG_OFF_REASON

        progress = replace(
            inputs,
            start_after=page.next_cursor,
            seen=inputs.seen + len(page.candidates),
            copied=inputs.copied + copied,
            skipped=inputs.skipped + skipped,
            failed=inputs.failed + failed,
        )
        workflow.logger.info(
            "conversation_backfill.page_done",
            extra={
                "cursor": progress.start_after,
                "page_size": len(page.candidates),
                "seen": progress.seen,
                "copied": progress.copied,
                "skipped": progress.skipped,
                "failed": progress.failed,
                "dry_run": inputs.dry_run,
            },
        )

        # A page where the flag refused every copy means the kill switch is off. Walking on
        # would read every remaining conversation for nothing.
        if page.candidates and flag_off == len(page.candidates):
            return self._summary(progress, "kill_switch")
        if page.exhausted:
            return self._summary(progress, "exhausted")

        if inputs.pause_seconds > 0:
            await workflow.sleep(timedelta(seconds=inputs.pause_seconds))
        workflow.continue_as_new(progress)

    async def _copy_page(
        self, candidates: list[BackfillCandidate], concurrency: int
    ) -> list[MirrorActivityResult | BaseException]:
        slots = asyncio.Semaphore(concurrency)

        async def copy(candidate: BackfillCandidate) -> MirrorActivityResult:
            async with slots:
                return await workflow.execute_activity(
                    mirror_conversation_to_task_activity,
                    MirrorConversationInputs(
                        team_id=candidate.team_id,
                        user_id=candidate.user_id,
                        conversation_id=candidate.conversation_id,
                    ),
                    start_to_close_timeout=COPY_ACTIVITY_TIMEOUT,
                    retry_policy=ACTIVITY_RETRY_POLICY,
                )

        return await asyncio.gather(*(copy(candidate) for candidate in candidates), return_exceptions=True)

    @staticmethod
    def _summary(progress: ConversationBackfillInputs, stopped_because: str) -> ConversationBackfillSummary:
        return ConversationBackfillSummary(
            seen=progress.seen,
            copied=progress.copied,
            skipped=progress.skipped,
            failed=progress.failed,
            last_cursor=progress.start_after,
            stopped_because=stopped_because,
        )


WORKFLOWS = [ConversationBackfillWorkflow]
ACTIVITIES = [list_conversations_to_backfill_activity, mirror_conversation_to_task_activity]
