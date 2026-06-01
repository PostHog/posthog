from typing import cast

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import exceptions
from rest_framework.parsers import JSONParser
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from products.posthog_ai.backend.context_wrapper import MAX_ATTACHED_ITEMS, MAX_TEXT_LENGTH
from products.posthog_ai.backend.message_routing import handle_sandbox_message
from products.tasks.backend.models import Task, TaskRun

from ee.models.assistant import Conversation

ROUTING = "products.posthog_ai.backend.message_routing"


class TestHandleSandboxMessage(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            agent_runtime=Conversation.AgentRuntime.SANDBOX,
        )

    def _request(self, data: dict) -> Request:
        factory = APIRequestFactory()
        django_request = factory.post("/sandbox/", data, format="json")
        request = cast(Request, Request(django_request, parsers=[JSONParser()]))
        request.user = self.user
        return request

    def _stub_task(self) -> tuple[Task, TaskRun]:
        task = Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=Task.OriginProduct.POSTHOG_AI,
            created_by=self.user,
        )
        run = task.create_run(mode="interactive")
        return task, run

    def _patches(self, task: Task):
        return (
            patch.object(Task, "create_and_run", return_value=task),
            patch(f"{ROUTING}.execute_task_processing_workflow"),
            patch(f"{ROUTING}.build_posthog_ai_system_prompt", return_value="SYS"),
            patch(f"{ROUTING}.report_user_action"),
        )

    def test_first_message_creates_run_and_persists_task(self):
        task, run = self._stub_task()
        car, workflow, sysprompt, telemetry = self._patches(task)
        with car as m_car, workflow as m_workflow, sysprompt, telemetry as m_telemetry:
            request = self._request(
                {
                    "content": "Why did checkout drop?",
                    "trace_id": "trace-1",
                    "attached_context": [{"type": "dashboard", "id": 123, "name": "Funnel"}],
                }
            )
            response = handle_sandbox_message(request, self.conversation)

        assert response.status_code == 200
        assert response.data["task_id"] == str(task.id)
        assert response.data["run_id"] == str(run.id)
        assert response.data["just_created_run"] is True
        assert response.data["trace_id"] == "trace-1"

        # Task.create_and_run called with the PostHog AI origin and no repo / no PR.
        _, kwargs = m_car.call_args
        assert kwargs["origin_product"] == Task.OriginProduct.POSTHOG_AI
        assert kwargs["repository"] is None
        assert kwargs["create_pr"] is False
        assert kwargs["mode"] == "interactive"
        assert kwargs["start_workflow"] is False

        # Run state enriched with the PostHog AI per-Run keys; full undeduped context.
        run.refresh_from_db()
        assert run.state["systemPrompt"] == "SYS"
        assert run.state["initial_permission_mode"] == "default"
        assert run.state["attached_context"] == [{"type": "dashboard", "id": 123, "name": "Funnel"}]
        assert "<posthog_context>" in run.state["pending_user_message"]
        assert run.state["pending_user_message"].endswith("Why did checkout drop?")

        self.conversation.refresh_from_db()
        assert self.conversation.task_id == task.id

        m_workflow.assert_called_once()
        m_telemetry.assert_called_once()

    def test_first_message_without_context_forwards_bare_content(self):
        task, run = self._stub_task()
        car, workflow, sysprompt, telemetry = self._patches(task)
        with car, workflow, sysprompt, telemetry:
            request = self._request({"content": "Hello", "trace_id": "t"})
            handle_sandbox_message(request, self.conversation)

        run.refresh_from_db()
        assert run.state["pending_user_message"] == "Hello"
        assert run.state["attached_context"] == []

    def test_missing_content_raises(self):
        request = self._request({"trace_id": "t"})
        with self.assertRaises(exceptions.ValidationError):
            handle_sandbox_message(request, self.conversation)

    def test_unknown_attached_context_type_raises(self):
        request = self._request({"content": "x", "attached_context": [{"type": "bogus", "id": 1}]})
        with self.assertRaises(exceptions.ValidationError):
            handle_sandbox_message(request, self.conversation)

    def test_dashboard_id_must_be_integer(self):
        request = self._request({"content": "x", "attached_context": [{"type": "dashboard", "id": "abc"}]})
        with self.assertRaises(exceptions.ValidationError):
            handle_sandbox_message(request, self.conversation)

    def test_attached_context_item_cap(self):
        items = [{"type": "insight", "id": str(i)} for i in range(MAX_ATTACHED_ITEMS + 1)]
        request = self._request({"content": "x", "attached_context": items})
        with self.assertRaises(exceptions.ValidationError):
            handle_sandbox_message(request, self.conversation)

    def test_text_length_cap(self):
        request = self._request(
            {"content": "x", "attached_context": [{"type": "text", "value": "a" * (MAX_TEXT_LENGTH + 1)}]}
        )
        with self.assertRaises(exceptions.ValidationError):
            handle_sandbox_message(request, self.conversation)

    def test_followup_not_yet_supported(self):
        task, _ = self._stub_task()
        self.conversation.task = task
        self.conversation.save(update_fields=["task"])
        request = self._request({"content": "follow up", "trace_id": "t"})
        with self.assertRaises(exceptions.ValidationError):
            handle_sandbox_message(request, self.conversation)
