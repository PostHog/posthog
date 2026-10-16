import uuid
import asyncio
from dataclasses import dataclass, field

import pytest
from posthog.test.base import APIBaseTest

from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.posthog_ai.backend.models.assistant import Conversation
from products.posthog_ai.backend.temporal.activities import MirrorActivityResult, MirrorConversationInputs
from products.posthog_ai.backend.temporal.backfill import (
    BackfillCandidate,
    ConversationBackfillInputs,
    ConversationBackfillWorkflow,
    ListCandidatesInputs,
    ListCandidatesOutput,
    list_candidates,
)
from products.tasks.backend.models import Task


class TestListCandidates(APIBaseTest):
    def _conversation(self, **overrides) -> Conversation:
        fields = {"user": self.user, "team": self.team, "agent_runtime": Conversation.AgentRuntime.LANGGRAPH}
        fields.update(overrides)
        return Conversation.objects.create(**fields)

    def _page(
        self, start_after: str | None = None, limit: int = 10, end_before: str | None = None
    ) -> ListCandidatesOutput:
        return list_candidates(ListCandidatesInputs(start_after=start_after, limit=limit, end_before=end_before))

    def test_lists_only_langgraph_assistant_chats_without_a_task(self) -> None:
        eligible = self._conversation()
        task = Task.objects.create(
            team=self.team, title="t", description="", origin_product=Task.OriginProduct.POSTHOG_AI
        )
        self._conversation(task=task)
        self._conversation(agent_runtime=Conversation.AgentRuntime.SANDBOX)
        self._conversation(deleted=True)
        self._conversation(is_internal=True)
        self._conversation(type=Conversation.Type.TOOL_CALL)

        page = self._page()

        assert page.candidates == [
            BackfillCandidate(conversation_id=str(eligible.id), team_id=self.team.id, user_id=self.user.id)
        ]
        assert page.next_cursor == str(eligible.id)
        assert page.exhausted is True

    def test_pages_in_id_order_from_the_cursor(self) -> None:
        ids = sorted(str(self._conversation().id) for _ in range(3))

        first = self._page(limit=2)
        assert [c.conversation_id for c in first.candidates] == ids[:2]
        assert first.next_cursor == ids[1]
        assert first.exhausted is False

        second = self._page(start_after=first.next_cursor, limit=2)
        assert [c.conversation_id for c in second.candidates] == ids[2:]
        assert second.exhausted is True

        empty = self._page(start_after=second.next_cursor, limit=2)
        assert empty.candidates == []
        assert empty.next_cursor == ids[2]
        assert empty.exhausted is True

        bounded = self._page(start_after=ids[0], limit=10, end_before=ids[2])
        assert [c.conversation_id for c in bounded.candidates] == ids[1:2]
        assert bounded.exhausted is True


@dataclass(frozen=False)
class FakeCopies:
    pages: list[list[str]]
    # conversation id -> "copied" | a skipped reason | "error"
    outcomes: dict[str, str] = field(default_factory=dict)
    copied_ids: list[str] = field(default_factory=list)
    in_flight: int = 0
    max_in_flight: int = 0
    list_bounds: list[str | None] = field(default_factory=list)

    def activities(self) -> list:
        fake = self

        @activity.defn(name="list_conversations_to_backfill_activity")
        async def list_activity(inputs: ListCandidatesInputs) -> ListCandidatesOutput:
            fake.list_bounds.append(inputs.end_before)
            page_index = 0 if inputs.start_after is None else fake._page_after(inputs.start_after)
            ids = fake.pages[page_index] if page_index < len(fake.pages) else []
            candidates = [BackfillCandidate(conversation_id=i, team_id=1, user_id=1) for i in ids]
            return ListCandidatesOutput(
                candidates=candidates,
                next_cursor=ids[-1] if ids else inputs.start_after,
                exhausted=len(ids) < inputs.limit,
            )

        @activity.defn(name="mirror_conversation_to_task_activity")
        async def copy_activity(inputs: MirrorConversationInputs) -> MirrorActivityResult:
            fake.in_flight += 1
            fake.max_in_flight = max(fake.max_in_flight, fake.in_flight)
            try:
                await asyncio.sleep(0.01)
                fake.copied_ids.append(inputs.conversation_id)
                outcome = fake.outcomes.get(inputs.conversation_id, "copied")
                if outcome == "error":
                    raise ApplicationError("boom", non_retryable=True)
                if outcome == "copied":
                    return MirrorActivityResult(skipped_reason=None, appended_frames=2)
                return MirrorActivityResult(skipped_reason=outcome, appended_frames=0)
            finally:
                fake.in_flight -= 1

        return [list_activity, copy_activity]

    def _page_after(self, cursor: str) -> int:
        for index, page in enumerate(self.pages):
            if page and page[-1] == cursor:
                return index + 1
        return len(self.pages)


async def _run(fake: FakeCopies, inputs: ConversationBackfillInputs):
    async with (
        await WorkflowEnvironment.start_time_skipping() as env,
        Worker(
            env.client,
            task_queue="backfill-test",
            workflows=[ConversationBackfillWorkflow],
            activities=fake.activities(),
            workflow_runner=UnsandboxedWorkflowRunner(),
        ),
    ):
        return await env.client.execute_workflow(
            ConversationBackfillWorkflow.run,
            inputs,
            id=str(uuid.uuid4()),
            task_queue="backfill-test",
        )


@pytest.mark.asyncio
async def test_walks_every_page_and_counts_each_outcome() -> None:
    fake = FakeCopies(pages=[["a", "b"], ["c", "d"], ["e"]], outcomes={"b": "no_messages", "d": "error"})

    summary = await _run(fake, ConversationBackfillInputs(batch_size=2, concurrency=2, end_before="z"))

    assert sorted(fake.copied_ids) == ["a", "b", "c", "d", "e"]
    assert fake.list_bounds == ["z", "z", "z"]
    assert (summary.seen, summary.copied, summary.skipped, summary.failed) == (5, 3, 1, 1)
    assert summary.last_cursor == "e"
    assert summary.stopped_because == "exhausted"


@pytest.mark.asyncio
async def test_keeps_at_most_concurrency_copies_in_flight() -> None:
    fake = FakeCopies(pages=[["a", "b", "c", "d", "e", "f"]])

    await _run(fake, ConversationBackfillInputs(batch_size=6, concurrency=2))

    assert fake.max_in_flight == 2


@pytest.mark.asyncio
async def test_dry_run_reads_pages_but_copies_nothing() -> None:
    fake = FakeCopies(pages=[["a", "b"], ["c"]])

    summary = await _run(fake, ConversationBackfillInputs(batch_size=2, dry_run=True))

    assert fake.copied_ids == []
    assert (summary.seen, summary.copied) == (3, 0)
    assert summary.stopped_because == "exhausted"


@pytest.mark.asyncio
async def test_stops_when_the_kill_switch_refuses_a_whole_page() -> None:
    fake = FakeCopies(pages=[["a", "b"], ["c", "d"]], outcomes={"a": "flag", "b": "flag"})

    summary = await _run(fake, ConversationBackfillInputs(batch_size=2))

    assert sorted(fake.copied_ids) == ["a", "b"]
    assert summary.stopped_because == "kill_switch"
    assert summary.last_cursor == "b"


@pytest.mark.asyncio
async def test_resumes_from_the_given_cursor() -> None:
    fake = FakeCopies(pages=[["a", "b"], ["c", "d"]])

    summary = await _run(fake, ConversationBackfillInputs(start_after="b", batch_size=2))

    assert sorted(fake.copied_ids) == ["c", "d"]
    assert summary.seen == 2
