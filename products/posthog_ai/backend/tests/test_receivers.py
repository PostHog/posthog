from posthog.test.base import APIBaseTest

from parameterized import parameterized

from products.posthog_ai.backend.models.assistant import Conversation
from products.tasks.backend.models import Task, TaskRun


class TestConversationFollowsTaskRun(APIBaseTest):
    def _linked_conversation(self, origin_product: str) -> tuple[Conversation, Task]:
        task = Task.objects.create(
            team=self.team, title="t", description="d", origin_product=origin_product, created_by=self.user
        )
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, agent_runtime=Conversation.AgentRuntime.LANGGRAPH, task=task
        )
        return conversation, task

    @parameterized.expand(
        [
            ("import_run", {"imported_from": "conversation"}, Conversation.AgentRuntime.LANGGRAPH),
            ("real_run", {}, Conversation.AgentRuntime.SANDBOX),
            ("warm_run", {"await_user_message": True}, Conversation.AgentRuntime.SANDBOX),
        ]
    )
    def test_only_a_run_that_is_not_the_import_marks_the_conversation_sandbox(
        self, _name: str, state: dict, expected: str
    ) -> None:
        conversation, task = self._linked_conversation(Task.OriginProduct.POSTHOG_AI)
        TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.QUEUED, state=state)
        conversation.refresh_from_db()
        assert conversation.agent_runtime == expected

    def test_runs_of_other_products_leave_the_conversation_alone(self) -> None:
        conversation, task = self._linked_conversation(Task.OriginProduct.USER_CREATED)
        TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.QUEUED, state={})
        conversation.refresh_from_db()
        assert conversation.agent_runtime == Conversation.AgentRuntime.LANGGRAPH
