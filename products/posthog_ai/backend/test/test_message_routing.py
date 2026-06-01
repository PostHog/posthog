from typing import cast

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import exceptions
from rest_framework.parsers import JSONParser
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from products.posthog_ai.backend.context_wrapper import MAX_ATTACHED_ITEMS, MAX_TEXT_LENGTH
from products.posthog_ai.backend.message_routing import handle_sandbox_cancel, handle_sandbox_message
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

    def _attach_task(self, task: Task) -> None:
        self.conversation.task = task
        self.conversation.save(update_fields=["task"])

    def test_in_progress_followup_signals_existing_run(self):
        task, run = self._stub_task()
        run.status = TaskRun.Status.IN_PROGRESS
        run.save(update_fields=["status"])
        self._attach_task(task)

        with (
            patch(f"{ROUTING}.signal_task_followup_message") as m_signal,
            patch(f"{ROUTING}.report_user_action") as m_telemetry,
            patch.object(TaskRun, "append_log") as m_append,
        ):
            request = self._request(
                {
                    "content": "and the mobile funnel?",
                    "trace_id": "trace-2",
                    "attached_context": [{"type": "insight", "id": "abc"}],
                }
            )
            response = handle_sandbox_message(request, self.conversation)

        assert response.status_code == 200
        assert response.data["task_id"] == str(task.id)
        assert response.data["run_id"] == str(run.id)
        assert response.data["just_created_run"] is False
        assert response.data["run_status"] == TaskRun.Status.IN_PROGRESS

        # The live workflow is signalled, no new Run created.
        m_signal.assert_called_once()
        signal_args, _ = m_signal.call_args
        assert signal_args[0] == run.workflow_id
        assert "and the mobile funnel?" in signal_args[1]
        assert task.runs.count() == 1

        # The follow-up is logged with the full undeduped attached_context on _meta.
        m_append.assert_called_once()
        logged_entries = m_append.call_args[0][0]
        meta = logged_entries[0]["notification"]["params"]["_meta"]
        assert meta["attached_context"] == [{"type": "insight", "id": "abc"}]
        m_telemetry.assert_called_once()

    def test_terminal_followup_creates_new_run_with_resume(self):
        task, run = self._stub_task()
        run.status = TaskRun.Status.COMPLETED
        run.state = {**(run.state or {}), "snapshot_external_id": "snap-9"}
        run.save(update_fields=["status", "state"])
        self._attach_task(task)

        with (
            patch(f"{ROUTING}.execute_task_processing_workflow") as m_workflow,
            patch(f"{ROUTING}.build_posthog_ai_system_prompt", return_value="SYS"),
            patch(f"{ROUTING}.report_user_action") as m_telemetry,
        ):
            request = self._request({"content": "resume please", "trace_id": "trace-3"})
            response = handle_sandbox_message(request, self.conversation)

        assert response.status_code == 200
        assert response.data["task_id"] == str(task.id)
        assert response.data["just_created_run"] is True

        new_run = task.runs.order_by("-created_at").first()
        assert new_run is not None
        assert str(new_run.id) == response.data["run_id"]
        assert str(new_run.id) != str(run.id)
        assert new_run.state["resume_from_run_id"] == str(run.id)
        assert new_run.state["snapshot_external_id"] == "snap-9"
        assert new_run.state["systemPrompt"] == "SYS"
        assert new_run.state["initial_permission_mode"] == "default"
        assert "resume please" in new_run.state["pending_user_message"]

        m_workflow.assert_called_once()
        assert m_workflow.call_args.kwargs["run_id"] == str(new_run.id)
        m_telemetry.assert_called_once()

    def test_dedupes_entities_named_in_prior_run_state(self):
        task, run = self._stub_task()
        run.status = TaskRun.Status.COMPLETED
        run.state = {**(run.state or {}), "attached_context": [{"type": "dashboard", "id": 7}]}
        run.save(update_fields=["status", "state"])
        self._attach_task(task)

        with (
            patch(f"{ROUTING}.execute_task_processing_workflow"),
            patch(f"{ROUTING}.build_posthog_ai_system_prompt", return_value="SYS"),
            patch(f"{ROUTING}.report_user_action"),
            patch(f"{ROUTING}.object_storage.read", return_value=""),
        ):
            request = self._request(
                {
                    "content": "again",
                    "attached_context": [{"type": "dashboard", "id": 7}, {"type": "insight", "id": "new"}],
                }
            )
            handle_sandbox_message(request, self.conversation)

        new_run = task.runs.order_by("-created_at").first()
        assert new_run is not None
        wrapped = new_run.state["pending_user_message"]
        # The already-seen dashboard is dropped from the rendered block; the new insight stays.
        assert "Dashboard #7" not in wrapped
        assert "Insight #new" in wrapped
        # The structured record keeps the full undeduped list.
        assert new_run.state["attached_context"] == [
            {"type": "dashboard", "id": 7},
            {"type": "insight", "id": "new"},
        ]

    def test_no_current_run_raises(self):
        task = Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=Task.OriginProduct.POSTHOG_AI,
            created_by=self.user,
        )
        self._attach_task(task)
        request = self._request({"content": "x"})
        with self.assertRaises(exceptions.ValidationError):
            handle_sandbox_message(request, self.conversation)


class TestHandleSandboxCancel(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            agent_runtime=Conversation.AgentRuntime.SANDBOX,
        )

    def _task_with_run(self, status: str) -> tuple[Task, TaskRun]:
        task = Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=Task.OriginProduct.POSTHOG_AI,
            created_by=self.user,
        )
        run = task.create_run(mode="interactive")
        run.status = status
        run.save(update_fields=["status"])
        self.conversation.task = task
        self.conversation.save(update_fields=["task"])
        return task, run

    def test_cancel_delegates_to_command_path(self):
        task, run = self._task_with_run(TaskRun.Status.IN_PROGRESS)

        def _mark_cancelled(target_run):
            TaskRun.objects.filter(id=target_run.id).update(status=TaskRun.Status.CANCELLED)

        with patch(f"{ROUTING}.send_cancel", side_effect=_mark_cancelled) as m_cancel:
            response = handle_sandbox_cancel(self.conversation)

        assert response.status_code == 200
        assert response.data["task_id"] == str(task.id)
        assert response.data["run_id"] == str(run.id)
        assert response.data["run_status"] == TaskRun.Status.CANCELLED
        m_cancel.assert_called_once()

    def test_cancel_terminal_run_is_idempotent(self):
        task, run = self._task_with_run(TaskRun.Status.COMPLETED)
        with patch(f"{ROUTING}.send_cancel") as m_cancel:
            response = handle_sandbox_cancel(self.conversation)
        assert response.status_code == 200
        assert response.data["run_status"] == TaskRun.Status.COMPLETED
        m_cancel.assert_not_called()

    def test_cancel_without_task_raises(self):
        with self.assertRaises(exceptions.ValidationError):
            handle_sandbox_cancel(self.conversation)
