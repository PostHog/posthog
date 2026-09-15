import json
from datetime import UTC, datetime
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog.schema import AssistantMessage, AssistantToolCall, AssistantToolCallMessage, ContextMessage, HumanMessage

from products.posthog_ai.backend.conversation_mirror import (
    LAST_MESSAGE_ID_KEY,
    MESSAGES_COPIED_KEY,
    CopyProgress,
    amirror_conversation,
    origin_key_for_conversation,
    project_legacy_messages,
)
from products.posthog_ai.backend.models.assistant import Conversation, ConversationCheckpoint
from products.posthog_ai.backend.temporal.activities import (
    MirrorConversationInputs,
    mirror_conversation_to_task_activity,
)
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.models import Task, TaskRun

from ee.hogai.api.serializers import (
    ConversationStateResult,
    aget_conversation_state as real_aget_conversation_state,
)
from ee.hogai.utils.types import AssistantState

SERIALIZERS = "ee.hogai.api.serializers"
MIRROR = "products.posthog_ai.backend.conversation_mirror"
ACTIVITIES = "products.posthog_ai.backend.temporal.activities"
MODELS = "products.tasks.backend.models"


def _method(frame: dict[str, Any]) -> str:
    notification = frame["notification"]
    method = notification["method"]
    if method == "session/update":
        return f"{method}:{notification['params']['update']['sessionUpdate']}"
    return method


VIZ_TURN: list[dict[str, Any]] = [
    {"type": "human", "id": "h1", "content": "Show me pageviews for the last 7 days"},
    {
        "type": "ai",
        "id": "a1",
        "content": "",
        "meta": {"thinking": [{"type": "thinking", "thinking": "A trends insight fits."}]},
        "tool_calls": [{"id": "toolu_1", "name": "create_insight", "args": {"insight_type": "trends"}}],
    },
    {
        "type": "ai/artifact",
        "id": "art1",
        "artifact_id": "Ab12",
        "content": {
            "content_type": "visualization",
            "name": "Pageviews",
            "description": "Daily",
            "query": {"kind": "TrendsQuery"},
        },
    },
    {"type": "tool", "id": "t1", "tool_call_id": "toolu_1", "content": "Name: Pageviews\nArtifact ID: Ab12"},
    {"type": "ai", "id": "a2", "content": "Here is your trend."},
]


class TestProjectLegacyMessages(APIBaseTest):
    @parameterized.expand(
        [
            (
                "viz_turn",
                VIZ_TURN,
                [
                    "_posthog/run_started",
                    "session/update:user_message_chunk",
                    "session/update:agent_thought_chunk",
                    "session/update:tool_call",
                    "session/update:tool_call_update",
                    "session/update:tool_call_update",
                    "session/update:agent_message",
                    "_posthog/turn_complete",
                ],
            ),
            (
                "failed_turn",
                [
                    {"type": "human", "id": "h1", "content": "hi"},
                    {"type": "ai/failure", "id": "f1", "content": "Oops"},
                ],
                [
                    "_posthog/run_started",
                    "session/update:user_message_chunk",
                    "_posthog/error",
                    "_posthog/turn_complete",
                ],
            ),
            (
                "unanswered_question_has_no_separator",
                [{"type": "human", "id": "h1", "content": "hi"}],
                ["_posthog/run_started", "session/update:user_message_chunk"],
            ),
            (
                "compaction_summary_is_a_user_turn",
                [
                    {"type": "context", "id": "c1", "content": "Summary of earlier turns"},
                    {"type": "human", "id": "h2", "content": "and now?"},
                    {"type": "ai", "id": "a2", "content": "Now this."},
                ],
                [
                    "_posthog/run_started",
                    "session/update:user_message_chunk",
                    "session/update:user_message_chunk",
                    "session/update:agent_message",
                    "_posthog/turn_complete",
                ],
            ),
        ]
    )
    def test_frame_sequence(self, _name: str, messages: list[dict[str, Any]], expected: list[str]) -> None:
        frames = project_legacy_messages(
            messages,
            run_id="run-1",
            include_run_start=True,
        )
        assert [_method(f) for f in frames] == expected

    def test_tool_frames_carry_exec_origin_and_artifact_query(self) -> None:
        frames = project_legacy_messages(
            VIZ_TURN,
            run_id="run-1",
            include_run_start=False,
        )
        user = frames[0]["notification"]["params"]
        assert user["sessionId"] == "run-1"
        assert user["update"]["_meta"] == {"importedUserPrompt": True, "imported": True}
        call, call_input, result = (f["notification"]["params"]["update"] for f in frames[2:5])
        assert call["_meta"]["claudeCode"]["toolName"] == "mcp__posthog__exec"
        assert call_input["rawInput"]["command"] == 'call create_insight {"insight_type": "trends"}'
        assert result["status"] == "completed"
        assert result["rawOutput"]["artifact_id"] == "Ab12"
        assert result["rawOutput"]["query"] == {"kind": "TrendsQuery"}
        # The sandbox resume parser reads tool history only from _meta.claudeCode.
        for frame in (call, call_input, result):
            assert frame["_meta"]["claudeCode"]["toolCallId"] == "toolu_1"
        assert call["_meta"]["claudeCode"]["toolInput"] == {"command": call_input["rawInput"]["command"]}
        assert result["_meta"]["claudeCode"]["toolResponse"] == result["rawOutput"]
        assert result["content"][0]["content"]["text"].startswith("Name: Pageviews")

    def test_context_messages_are_hidden_from_the_thread(self) -> None:
        frames = project_legacy_messages(
            [
                {"type": "context", "id": "c1", "content": "Summary of earlier turns"},
                {"type": "human", "id": "h2", "content": "and now?"},
            ],
            run_id="run-1",
            include_run_start=False,
        )
        summary, question = (f["notification"]["params"]["update"]["content"] for f in frames)
        assert summary == {"type": "text", "text": "Summary of earlier turns", "_meta": {"ui": {"hidden": True}}}
        assert question == {"type": "text", "text": "and now?"}

    def test_recordings_filters_ride_the_tool_result(self) -> None:
        filters = {"date_from": "-7d", "duration": [], "filter_group": {"type": "AND", "values": []}}
        messages: list[dict[str, Any]] = [
            {
                "type": "ai",
                "id": "a1",
                "content": "",
                "tool_calls": [
                    {"id": "c1", "name": "filter_session_recordings", "args": {"recordings_filters": filters}}
                ],
            },
            {"type": "tool", "id": "t1", "tool_call_id": "c1", "content": "Found 3 recordings"},
        ]
        frames = project_legacy_messages(
            messages,
            run_id="r",
            include_run_start=False,
        )
        assert frames[-2]["notification"]["params"]["update"]["rawOutput"]["filters"] == filters


class TestMirrorConversation(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.conversation = Conversation.objects.create(user=self.user, team=self.team, title="Pageviews chat")
        self.logs: dict[str, str] = {}
        self.state_messages: list[Any] = []
        self._patches = [
            patch(f"{SERIALIZERS}.aget_conversation_state", side_effect=self._aget_state),
            patch(f"{MODELS}.object_storage.read", side_effect=lambda key, **kw: self.logs.get(key)),
            patch(
                f"{MODELS}.object_storage.write",
                side_effect=lambda key, content, **kw: self.logs.__setitem__(key, content),
            ),
            patch(f"{MODELS}.object_storage.tag"),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    async def _aget_state(self, conversation: Conversation, team: Any, user: Any) -> ConversationStateResult:
        return ConversationStateResult(
            state=AssistantState(messages=self.state_messages), has_unsupported_content=False, interrupt_payloads={}
        )

    def _mirror(self):
        return async_to_sync(amirror_conversation)(self.conversation.id, self.team.id, self.user.id)

    def _log_methods(self) -> list[str]:
        (content,) = self.logs.values()
        return [_method(json.loads(line)) for line in content.strip().split("\n")]

    def test_first_touch_creates_task_and_import_run_then_appends(self) -> None:
        self.state_messages = [HumanMessage(content="hello", id="h1"), AssistantMessage(content="hi there", id="a1")]
        started_at = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
        Conversation.objects.filter(id=self.conversation.id).update(created_at=started_at)

        result = self._mirror()

        assert result.skipped_reason is None
        task = Task.objects.get(id=result.task_id)
        assert task.origin_key == origin_key_for_conversation(self.conversation.id)
        assert task.origin_product == Task.OriginProduct.POSTHOG_AI
        assert task.title == "Pageviews chat"
        assert task.channel_id is not None
        assert task.created_at == started_at
        self.conversation.refresh_from_db()
        assert self.conversation.task_id == task.id
        run = TaskRun.objects.get(id=result.run_id)
        assert run.status == TaskRun.Status.COMPLETED
        assert run.created_at == started_at
        assert run.state["imported_from"] == "conversation"
        assert run.state[MESSAGES_COPIED_KEY] == 2
        assert run.state[LAST_MESSAGE_ID_KEY] == "a1"
        assert run.completed_at == self.conversation.updated_at
        assert self._log_methods() == [
            "_posthog/run_started",
            "session/update:user_message_chunk",
            "session/update:agent_message",
            "_posthog/turn_complete",
        ]

        self.state_messages = [
            *self.state_messages,
            HumanMessage(content="more", id="h2"),
            AssistantMessage(content="sure", id="a2"),
        ]
        continued_at = datetime(2026, 5, 2, 9, 30, tzinfo=UTC)
        Conversation.objects.filter(id=self.conversation.id).update(updated_at=continued_at)
        second = self._mirror()

        assert (second.task_id, second.run_id) == (result.task_id, result.run_id)
        assert second.appended_frames == 3
        assert self._log_methods()[-3:] == [
            "session/update:user_message_chunk",
            "session/update:agent_message",
            "_posthog/turn_complete",
        ]
        run.refresh_from_db()
        assert run.state[MESSAGES_COPIED_KEY] == 4
        assert run.state[LAST_MESSAGE_ID_KEY] == "a2"
        assert run.completed_at == continued_at
        assert TaskRun.objects.filter(task_id=result.task_id).count() == 1

        third = self._mirror()
        assert third.appended_frames == 0
        assert len(self._log_methods()) == 7

    def test_artifact_query_survives_the_round_trip(self) -> None:
        self.state_messages = [
            HumanMessage(content="pageviews?", id="h1"),
            AssistantMessage(
                content="",
                id="a1",
                tool_calls=[AssistantToolCall(id="toolu_1", name="create_insight", args={"insight_type": "trends"})],
            ),
            AssistantToolCallMessage(content="Name: Pageviews", id="t1", tool_call_id="toolu_1"),
            AssistantMessage(content="done", id="a2"),
        ]
        result = self._mirror()
        assert result.appended_frames == 7
        assert "session/update:tool_call_update" in self._log_methods()

    def test_compaction_that_keeps_the_last_copied_message_copies_only_what_follows(self) -> None:
        self.state_messages = [
            HumanMessage(content="one", id="h1"),
            AssistantMessage(content="1", id="a1"),
            HumanMessage(content="two", id="h2"),
            AssistantMessage(content="2", id="a2"),
        ]
        first = self._mirror()
        # Compaction dropped the first turn from the stored list; the anchor a2 is still there.
        self.state_messages = [
            HumanMessage(content="two", id="h2"),
            AssistantMessage(content="2", id="a2"),
            HumanMessage(content="three", id="h3"),
            AssistantMessage(content="3", id="a3"),
        ]
        second = self._mirror()
        assert second.appended_frames == 3
        assert self._log_methods().count("session/update:user_message_chunk") == 3
        run = TaskRun.objects.get(id=first.run_id)
        assert run.state[LAST_MESSAGE_ID_KEY] == "a3"
        assert run.state[MESSAGES_COPIED_KEY] == 6

    def test_compaction_that_dropped_the_last_copied_message_copies_the_whole_window(self) -> None:
        self.state_messages = [HumanMessage(content="one", id="h1"), AssistantMessage(content="1", id="a1")]
        self._mirror()
        # Everything copied so far was compacted away; the window holds only newer turns.
        self.state_messages = [HumanMessage(content="four", id="h4"), AssistantMessage(content="4", id="a4")]
        second = self._mirror()
        assert second.appended_frames == 3
        assert self._log_methods().count("session/update:user_message_chunk") == 2
        assert TaskRun.objects.get(id=second.run_id).state[LAST_MESSAGE_ID_KEY] == "a4"

    def test_a_concurrent_copy_that_already_moved_the_run_on_is_not_appended_again(self):
        self.state_messages = [HumanMessage(content="hello", id="h1"), AssistantMessage(content="hi", id="a1")]
        first = self._mirror()
        # A second copier that read the run before the first one wrote it sees nothing copied yet.
        with patch(f"{MIRROR}._read_copy_progress", return_value=CopyProgress(message_count=0, last_message_id=None)):
            second = self._mirror()
        assert second.skipped_reason == "state_mismatch"
        assert second.run_id == first.run_id
        assert len(self._log_methods()) == 4

    def test_retry_after_a_failed_state_write_does_not_copy_the_turn_twice(self):
        self.state_messages = [HumanMessage(content="hello", id="h1"), AssistantMessage(content="hi", id="a1")]
        # The log append succeeds, then the state write fails and rolls the transaction back.
        original_save = TaskRun.save

        def save_but_fail_the_progress_write(run, *args, **kwargs):
            if kwargs.get("update_fields") == ["state", "completed_at"]:
                raise RuntimeError("db down")
            return original_save(run, *args, **kwargs)

        with patch.object(TaskRun, "save", save_but_fail_the_progress_write), self.assertRaises(RuntimeError):
            self._mirror()
        assert len(self._log_methods()) == 4
        assert TaskRun.objects.get(state__has_key="imported_from").state[MESSAGES_COPIED_KEY] == 0

        result = self._mirror()

        assert result.appended_frames == 4
        assert len(self._log_methods()) == 4
        assert TaskRun.objects.get(id=result.run_id).state[MESSAGES_COPIED_KEY] == 2

    def test_a_turn_still_in_progress_waits_for_the_next_copy(self) -> None:
        self.state_messages = [
            HumanMessage(content="hello", id="h1"),
            AssistantMessage(content="hi", id="a1"),
            HumanMessage(content="chart it", id="h2"),
            AssistantMessage(
                content="",
                id="a2",
                tool_calls=[AssistantToolCall(id="c1", name="create_insight", args={})],
            ),
        ]
        first = self._mirror()
        assert first.appended_frames == 4
        assert TaskRun.objects.get(id=first.run_id).state[MESSAGES_COPIED_KEY] == 2

        self.state_messages = [
            *self.state_messages,
            AssistantToolCallMessage(content="done", id="t1", tool_call_id="c1"),
            AssistantMessage(content="here it is", id="a3"),
        ]
        second = self._mirror()
        assert second.run_id == first.run_id
        assert TaskRun.objects.get(id=first.run_id).state[MESSAGES_COPIED_KEY] == 6
        assert self._log_methods().count("session/update:user_message_chunk") == 2

    def test_concurrent_first_touches_share_one_import_run(self) -> None:
        self.state_messages = [HumanMessage(content="hello", id="h1"), AssistantMessage(content="hi", id="a1")]
        first = self._mirror()
        assert first.task_id is not None
        duplicate = tasks_facade.create_imported_task_run(
            first.task_id,
            self.team.id,
            state={"imported_from": "conversation"},
            created_at=self.conversation.created_at or timezone.now(),
            completed_at=timezone.now(),
        )
        assert duplicate.id == first.run_id
        assert TaskRun.objects.filter(task_id=first.task_id, state__has_key="imported_from").count() == 1

    def test_deleting_the_task_deletes_the_chat_and_stops_the_copy(self) -> None:
        self.state_messages = [HumanMessage(content="hello", id="h1"), AssistantMessage(content="hi", id="a1")]
        first = self._mirror()
        assert first.task_id is not None

        assert tasks_facade.soft_delete_task(first.task_id, self.team.id, self.user.id)

        self.conversation.refresh_from_db()
        assert self.conversation.deleted
        Conversation.objects.filter(id=self.conversation.id).update(deleted=False)
        self.state_messages = [
            *self.state_messages,
            HumanMessage(content="more", id="h2"),
            AssistantMessage(content="ok", id="a2"),
        ]
        assert self._mirror().skipped_reason == "task_deleted"
        assert len(self._log_methods()) == 4

    def test_compaction_summary_is_copied(self) -> None:
        self.state_messages = [
            ContextMessage(content="Summary: the user asked about pageviews", id="c1"),
            HumanMessage(content="and by device?", id="h2"),
            AssistantMessage(content="Mostly mobile.", id="a2"),
        ]

        result = self._mirror()

        assert TaskRun.objects.get(id=result.run_id).state[MESSAGES_COPIED_KEY] == 3
        (content,) = self.logs.values()
        assert '"hidden": true' in content and "Summary: the user asked about pageviews" in content

    def test_moved_conversation_renders_no_checkpoint_history(self):
        # Once the history is in the task's import run, the checkpoint must not render as well.
        self.state_messages = [HumanMessage(content="hello", id="h1"), AssistantMessage(content="hi", id="a1")]
        self._mirror()
        ConversationCheckpoint.objects.create(thread=self.conversation)
        Conversation.objects.filter(id=self.conversation.id).update(agent_runtime=Conversation.AgentRuntime.SANDBOX)
        self.conversation.refresh_from_db()

        with patch(f"{SERIALIZERS}.capture_exception") as capture:
            result = async_to_sync(real_aget_conversation_state)(self.conversation, self.team, self.user)

        assert result.state is None
        capture.assert_not_called()

    @parameterized.expand(
        [
            ("sandbox_runtime", {"agent_runtime": Conversation.AgentRuntime.SANDBOX}, "runtime"),
            ("tool_call_type", {"type": Conversation.Type.TOOL_CALL}, "type"),
            ("deleted", {"deleted": True}, "deleted"),
        ]
    )
    def test_skips_conversations_that_must_not_be_mirrored(
        self, _name: str, setup: dict[str, Any], reason: str
    ) -> None:
        self.state_messages = [HumanMessage(content="hello", id="h1"), AssistantMessage(content="hi", id="a1")]
        for field, value in setup.items():
            setattr(self.conversation, field, value)
        self.conversation.save()
        result = self._mirror()
        assert result.skipped_reason == reason
        assert not Task.objects.filter(team=self.team).exists()
        assert self.logs == {}


class TestMirrorActivity(APIBaseTest):
    def test_kill_switch_skips_the_copy(self) -> None:
        inputs = MirrorConversationInputs(team_id=self.team.id, user_id=self.user.id, conversation_id="c")
        with (
            patch(f"{ACTIVITIES}.has_conversation_task_mirror_feature_flag", return_value=False),
            patch(f"{ACTIVITIES}.amirror_conversation") as m_mirror,
        ):
            async_to_sync(mirror_conversation_to_task_activity)(inputs)
        m_mirror.assert_not_called()
