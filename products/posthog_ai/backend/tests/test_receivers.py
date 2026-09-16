from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.posthog_ai.backend.conversation_mirror import MirrorResult
from products.posthog_ai.backend.models.assistant import Conversation
from products.posthog_ai.backend.receivers import (
    COPY_BEHIND_MESSAGE,
    SANDBOX_MODE_REQUIRED_MESSAGE,
    catch_up_conversation_copy_before_run,
)
from products.tasks.backend.models import Task, TaskRun

FLAGS = "ee.hogai.utils.feature_flags"


class ConversationTaskTestMixin(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        for flag in ("has_sandbox_mode_feature_flag", "has_conversation_task_mirror_feature_flag"):
            p = patch(f"{FLAGS}.{flag}", return_value=True)
            p.start()
            self.addCleanup(p.stop)

    def _linked_conversation(self, origin_product: str = Task.OriginProduct.POSTHOG_AI) -> tuple[Conversation, Task]:
        task = Task.objects.create(
            team=self.team, title="t", description="d", origin_product=origin_product, created_by=self.user
        )
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, agent_runtime=Conversation.AgentRuntime.LANGGRAPH, task=task
        )
        return conversation, task


class TestConversationFollowsTaskRun(ConversationTaskTestMixin):
    @parameterized.expand(
        [
            ("import_run", {"imported_from": "conversation"}, Conversation.AgentRuntime.LANGGRAPH),
            ("warm_run", {"await_user_message": True}, Conversation.AgentRuntime.LANGGRAPH),
            ("real_run", {}, Conversation.AgentRuntime.SANDBOX),
        ]
    )
    def test_only_a_real_run_marks_the_conversation_sandbox(self, _name: str, state: dict, expected: str) -> None:
        conversation, task = self._linked_conversation()
        TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.QUEUED, state=state)
        conversation.refresh_from_db()
        assert conversation.agent_runtime == expected

    def test_runs_of_other_products_leave_the_conversation_alone(self) -> None:
        conversation, task = self._linked_conversation(Task.OriginProduct.USER_CREATED)
        TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.QUEUED, state={})
        conversation.refresh_from_db()
        assert conversation.agent_runtime == Conversation.AgentRuntime.LANGGRAPH

    def test_an_owner_without_sandbox_mode_keeps_the_langgraph_runtime(self) -> None:
        conversation, task = self._linked_conversation()
        with patch(f"{FLAGS}.has_sandbox_mode_feature_flag", return_value=False):
            TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.QUEUED, state={})
        conversation.refresh_from_db()
        assert conversation.agent_runtime == Conversation.AgentRuntime.LANGGRAPH


class TestCatchUpBeforeRun(ConversationTaskTestMixin):
    def _guard(self, task: Task) -> str | None:
        return catch_up_conversation_copy_before_run(str(task.id), self.team.id, self.user.id)

    def _copied(self, **kwargs) -> MirrorResult:
        defaults = {"skipped_reason": None, "task_id": None, "run_id": None, "appended_frames": 2}
        return MirrorResult(**{**defaults, **kwargs})

    def test_copies_the_missing_turns_then_lets_the_run_start(self) -> None:
        conversation, task = self._linked_conversation()
        with patch(f"products.posthog_ai.backend.conversation_mirror.amirror_conversation") as copy:
            copy.return_value = self._copied()
            assert self._guard(task) is None
        copy.assert_called_once_with(conversation.id, self.team.id, self.user.id)

    @parameterized.expand([("failed", RuntimeError("db down")), ("skipped", None)])
    def test_refuses_the_run_when_the_copy_did_not_catch_up(self, _name: str, error: Exception | None) -> None:
        _, task = self._linked_conversation()
        with patch(f"products.posthog_ai.backend.conversation_mirror.amirror_conversation") as copy:
            if error is not None:
                copy.side_effect = error
            else:
                copy.return_value = self._copied(skipped_reason="task_deleted")
            assert self._guard(task) == COPY_BEHIND_MESSAGE

    def test_refuses_the_run_for_an_owner_without_sandbox_mode(self) -> None:
        _, task = self._linked_conversation()
        with (
            patch(f"{FLAGS}.has_sandbox_mode_feature_flag", return_value=False),
            patch(f"products.posthog_ai.backend.conversation_mirror.amirror_conversation") as copy,
        ):
            assert self._guard(task) == SANDBOX_MODE_REQUIRED_MESSAGE
        copy.assert_not_called()

    def test_leaves_tasks_without_a_langgraph_chat_alone(self) -> None:
        conversation, task = self._linked_conversation()
        conversation.agent_runtime = Conversation.AgentRuntime.SANDBOX
        conversation.save()
        with patch(f"products.posthog_ai.backend.conversation_mirror.amirror_conversation") as copy:
            assert self._guard(task) is None
        copy.assert_not_called()
