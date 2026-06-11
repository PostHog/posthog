from contextlib import contextmanager

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import exceptions

from posthog.exceptions import Conflict

from products.posthog_ai.backend.context_wrapper import MAX_ATTACHED_ITEMS, MAX_TEXT_LENGTH
from products.posthog_ai.backend.message_routing import (
    MessageRoutingService,
    SandboxCommandError,
    lock_conversation_for_followup,
)
from products.posthog_ai.backend.models.assistant import Conversation
from products.posthog_ai.backend.system_prompt import PromptService
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.services.agent_command import CommandResult

ROUTING = "products.posthog_ai.backend.message_routing"


class TestHandleSandboxMessage(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            agent_runtime=Conversation.AgentRuntime.SANDBOX,
        )

    def _service(self) -> MessageRoutingService:
        return MessageRoutingService(self.conversation, self.user)

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
            patch.object(PromptService, "build", return_value="SYS"),
        )

    def test_first_message_creates_run_and_persists_task(self):
        task, run = self._stub_task()
        car, workflow, sysprompt = self._patches(task)
        with car as m_car, workflow as m_workflow, sysprompt:
            result = self._service().handle(
                {
                    "content": "Why did checkout drop?",
                    "trace_id": "trace-1",
                    "attached_context": [{"type": "dashboard", "id": 123, "name": "Funnel"}],
                }
            )

        assert result.task_id == str(task.id)
        assert result.run_id == str(run.id)
        assert result.just_created_run is True
        assert result.trace_id == "trace-1"

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
        _, wf_kwargs = m_workflow.call_args
        assert wf_kwargs["create_pr"] is False
        # The agent needs write scopes to create insights/dashboards/notebooks.
        assert wf_kwargs["posthog_mcp_scopes"] == "full"

    def test_first_message_without_context_forwards_bare_content(self):
        task, run = self._stub_task()
        car, workflow, sysprompt = self._patches(task)
        with car, workflow, sysprompt:
            self._service().handle({"content": "Hello", "trace_id": "t"})

        run.refresh_from_db()
        assert run.state["pending_user_message"] == "Hello"
        assert run.state["attached_context"] == []

    def test_missing_content_raises(self):
        with self.assertRaises(exceptions.ValidationError):
            self._service().handle({"trace_id": "t"})

    def test_unknown_attached_context_type_raises(self):
        with self.assertRaises(exceptions.ValidationError):
            self._service().handle({"content": "x", "attached_context": [{"type": "bogus", "id": 1}]})

    def test_dashboard_id_must_be_integer(self):
        with self.assertRaises(exceptions.ValidationError):
            self._service().handle({"content": "x", "attached_context": [{"type": "dashboard", "id": "abc"}]})

    def test_attached_context_item_cap(self):
        items = [{"type": "insight", "id": str(i)} for i in range(MAX_ATTACHED_ITEMS + 1)]
        with self.assertRaises(exceptions.ValidationError):
            self._service().handle({"content": "x", "attached_context": items})

    def test_text_length_cap(self):
        with self.assertRaises(exceptions.ValidationError):
            self._service().handle(
                {"content": "x", "attached_context": [{"type": "text", "value": "a" * (MAX_TEXT_LENGTH + 1)}]}
            )

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
            patch.object(TaskRun, "append_log") as m_append,
        ):
            result = self._service().handle(
                {
                    "content": "and the mobile funnel?",
                    "trace_id": "trace-2",
                    "attached_context": [{"type": "insight", "id": "abc"}],
                }
            )

        assert result.task_id == str(task.id)
        assert result.run_id == str(run.id)
        assert result.just_created_run is False
        assert result.run_status == TaskRun.Status.IN_PROGRESS
        # The routing endpoint reads this off the result for its "prompt sent" telemetry.
        assert result.attached_context_count == 1

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

    def test_terminal_followup_creates_new_run_with_resume(self):
        task, run = self._stub_task()
        run.status = TaskRun.Status.COMPLETED
        run.state = {**(run.state or {}), "snapshot_external_id": "snap-9"}
        run.save(update_fields=["status", "state"])
        self._attach_task(task)

        with (
            patch(f"{ROUTING}.execute_task_processing_workflow") as m_workflow,
            patch.object(PromptService, "build", return_value="SYS"),
        ):
            result = self._service().handle({"content": "resume please", "trace_id": "trace-3"})

        assert result.task_id == str(task.id)
        assert result.just_created_run is True

        new_run = task.runs.order_by("-created_at").first()
        assert new_run is not None
        assert str(new_run.id) == result.run_id
        assert str(new_run.id) != str(run.id)
        assert new_run.state["resume_from_run_id"] == str(run.id)
        assert new_run.state["snapshot_external_id"] == "snap-9"
        assert new_run.state["systemPrompt"] == "SYS"
        assert new_run.state["initial_permission_mode"] == "default"
        assert "resume please" in new_run.state["pending_user_message"]

        m_workflow.assert_called_once()
        assert m_workflow.call_args.kwargs["run_id"] == str(new_run.id)
        # The resumed agent keeps the same write scopes as the first message.
        assert m_workflow.call_args.kwargs["posthog_mcp_scopes"] == "full"

    def test_dedupes_entities_named_in_prior_run_state(self):
        task, run = self._stub_task()
        run.status = TaskRun.Status.COMPLETED
        run.state = {**(run.state or {}), "attached_context": [{"type": "dashboard", "id": 7}]}
        run.save(update_fields=["status", "state"])
        self._attach_task(task)

        with (
            patch(f"{ROUTING}.execute_task_processing_workflow"),
            patch.object(PromptService, "build", return_value="SYS"),
            patch(f"{ROUTING}.object_storage.read", return_value=""),
        ):
            self._service().handle(
                {
                    "content": "again",
                    "attached_context": [{"type": "dashboard", "id": 7}, {"type": "insight", "id": "new"}],
                }
            )

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
        with self.assertRaises(exceptions.ValidationError):
            self._service().handle({"content": "x"})

    def test_terminal_resume_conflicts_when_a_concurrent_followup_won(self):
        task, run = self._stub_task()
        run.status = TaskRun.Status.COMPLETED
        run.save(update_fields=["status"])
        self._attach_task(task)

        # By the time this request is granted the lock, a concurrent follow-up has already
        # created the in-progress successor — exactly the window the row lock serializes.
        @contextmanager
        def lock_granted_after_concurrent_winner(conversation_id: str, team_id: int):
            task.create_run(mode="interactive")
            self.conversation.refresh_from_db()
            yield self.conversation

        with (
            patch(f"{ROUTING}.lock_conversation_for_followup", side_effect=lock_granted_after_concurrent_winner),
            patch(f"{ROUTING}.execute_task_processing_workflow") as m_workflow,
            patch.object(PromptService, "build", return_value="SYS"),
        ):
            with self.assertRaises(Conflict):
                self._service().handle({"content": "resume please"})

        # The winner's successor is the only new run — no duplicate create, no workflow dispatch.
        assert task.runs.count() == 2
        m_workflow.assert_not_called()

    def test_terminal_resume_uses_freshest_terminal_run_after_lock(self):
        task, run = self._stub_task()
        run.status = TaskRun.Status.COMPLETED
        run.save(update_fields=["status"])
        self._attach_task(task)

        # The concurrent winner's successor already finished — the loser must resume from it,
        # not from the stale run it resolved before waiting on the lock.
        @contextmanager
        def lock_granted_after_winner_finished(conversation_id: str, team_id: int):
            successor = task.create_run(mode="interactive")
            successor.status = TaskRun.Status.COMPLETED
            successor.save(update_fields=["status"])
            self.conversation.refresh_from_db()
            yield self.conversation

        with (
            patch(f"{ROUTING}.lock_conversation_for_followup", side_effect=lock_granted_after_winner_finished),
            patch(f"{ROUTING}.execute_task_processing_workflow"),
            patch.object(PromptService, "build", return_value="SYS"),
        ):
            result = self._service().handle({"content": "resume please"})

        new_run = task.runs.order_by("-created_at").first()
        assert new_run is not None
        assert str(new_run.id) == result.run_id
        assert new_run.state["resume_from_run_id"] != str(run.id)


class TestHandleSandboxCancel(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            agent_runtime=Conversation.AgentRuntime.SANDBOX,
        )

    def _service(self) -> MessageRoutingService:
        return MessageRoutingService(self.conversation, self.user)

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

        with patch(f"{ROUTING}.send_cancel", return_value=CommandResult(success=True, status_code=200)) as m_cancel:
            result = self._service().cancel()

        # The command is delivered; the run stays live until the agent acts on it,
        # so the response reports the current (not yet terminal) status.
        assert result.task_id == str(task.id)
        assert result.run_id == str(run.id)
        assert result.run_status == TaskRun.Status.IN_PROGRESS
        # A live run was actually signalled — the routing endpoint emits cancellation telemetry.
        assert result.cancel_requested is True
        m_cancel.assert_called_once()

    def test_cancel_delivery_failure_raises_502(self):
        self._task_with_run(TaskRun.Status.IN_PROGRESS)

        with patch(
            f"{ROUTING}.send_cancel",
            return_value=CommandResult(success=False, status_code=0, error="connection refused"),
        ):
            with self.assertRaises(SandboxCommandError) as ctx:
                self._service().cancel()

        assert ctx.exception.status_code == 502

    def test_cancel_terminal_run_is_idempotent(self):
        task, run = self._task_with_run(TaskRun.Status.COMPLETED)
        with patch(f"{ROUTING}.send_cancel") as m_cancel:
            result = self._service().cancel()
        assert result.run_status == TaskRun.Status.COMPLETED
        # Nothing was cancelled, so no cancellation telemetry should fire.
        assert result.cancel_requested is False
        m_cancel.assert_not_called()

    def test_cancel_without_task_raises(self):
        with self.assertRaises(exceptions.ValidationError):
            self._service().cancel()


class TestLockConversationForFollowup(APIBaseTest):
    def test_lock_acquires_select_for_update_on_conversation(self):
        conversation = Conversation.objects.create(user=self.user, team=self.team)

        with patch(f"{ROUTING}.Conversation.objects") as mock_objects:
            mock_sfu = mock_objects.select_for_update.return_value
            mock_sfu.get.return_value = conversation

            with lock_conversation_for_followup(str(conversation.id), self.team.id) as locked:
                self.assertEqual(locked, conversation)

        mock_objects.select_for_update.assert_called_once_with()
        mock_sfu.get.assert_called_once_with(id=str(conversation.id), team_id=self.team.id)

    def test_lock_yields_the_conversation_row(self):
        conversation = Conversation.objects.create(user=self.user, team=self.team)

        with lock_conversation_for_followup(str(conversation.id), self.team.id) as locked:
            self.assertEqual(locked.id, conversation.id)
