from contextlib import contextmanager

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import exceptions

from posthog.exceptions import Conflict, QuotaLimitExceeded

from products.posthog_ai.backend.context_wrapper import MAX_ATTACHED_ITEMS, MAX_TEXT_LENGTH
from products.posthog_ai.backend.message_routing import (
    POSTHOG_AI_INTERACTION_ORIGIN,
    SANDBOX_INACTIVITY_TIMEOUT_SECONDS,
    SandboxSession,
    lock_conversation_for_followup,
)
from products.posthog_ai.backend.models.assistant import Conversation
from products.posthog_ai.backend.run_state import PostHogAIRunState
from products.posthog_ai.backend.services.system_prompt.service import PromptService
from products.tasks.backend.facade import warm as warm_facade
from products.tasks.backend.models import Task, TaskRun

ROUTING = "products.posthog_ai.backend.message_routing"
WARM = "products.tasks.backend.logic.services.warm"
SYS_PROMPT = {"type": "preset", "preset": "claude_code", "append": "SYS"}


class TestOpenSandboxMessage(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            agent_runtime=Conversation.AgentRuntime.SANDBOX,
        )

    def _service(self) -> SandboxSession:
        return SandboxSession(self.conversation, self.user)

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
            patch.object(PromptService, "build", return_value=SYS_PROMPT),
        )

    def test_first_message_creates_run_and_persists_task(self):
        task, run = self._stub_task()
        car, workflow, sysprompt = self._patches(task)
        with car as m_car, workflow as m_workflow, sysprompt:
            result = self._service().open(
                {
                    "content": "Why did checkout drop?",
                    "trace_id": "trace-1",
                    "attached_context": [{"type": "dashboard", "id": 123, "name": "Funnel"}],
                }
            )

        assert result is not None
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
        assert kwargs["interaction_origin"] == POSTHOG_AI_INTERACTION_ORIGIN
        # The sandbox session pins its short interactivity window as a per-task override.
        assert kwargs["inactivity_timeout_seconds"] == SANDBOX_INACTIVITY_TIMEOUT_SECONDS

        # Run state enriched with the PostHog AI per-Run keys; full undeduped context.
        run.refresh_from_db()
        assert run.state["interaction_origin"] == POSTHOG_AI_INTERACTION_ORIGIN
        assert run.state["systemPrompt"] == SYS_PROMPT
        assert run.state["initial_permission_mode"] == "auto"
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

    def test_first_message_threads_routed_repository(self):
        task, _ = self._stub_task()
        car, workflow, sysprompt = self._patches(task)
        with car as m_car, workflow, sysprompt:
            self._service().open({"content": "fix the SDK", "trace_id": "t"}, repository="posthog/posthog-js")

        _, kwargs = m_car.call_args
        assert kwargs["repository"] == "posthog/posthog-js"

    def test_first_message_honors_initial_permission_mode(self):
        task, run = self._stub_task()
        car, workflow, sysprompt = self._patches(task)
        with car, workflow, sysprompt:
            self._service().open(
                {
                    "content": "Use plan mode",
                    "trace_id": "trace-1",
                    "initial_permission_mode": "plan",
                }
            )

        run.refresh_from_db()
        assert run.state["initial_permission_mode"] == "plan"

    def test_first_message_without_context_forwards_bare_content(self):
        task, run = self._stub_task()
        car, workflow, sysprompt = self._patches(task)
        with car, workflow, sysprompt:
            self._service().open({"content": "Hello", "trace_id": "t"})

        run.refresh_from_db()
        assert run.state["pending_user_message"] == "Hello"
        assert run.state["attached_context"] == []

    def test_unknown_attached_context_type_raises(self):
        with self.assertRaises(exceptions.ValidationError):
            self._service().open({"content": "x", "attached_context": [{"type": "bogus", "id": 1}]})

    def test_dashboard_id_must_be_integer(self):
        with self.assertRaises(exceptions.ValidationError):
            self._service().open({"content": "x", "attached_context": [{"type": "dashboard", "id": "abc"}]})

    def test_attached_context_item_cap(self):
        items = [{"type": "insight", "id": str(i)} for i in range(MAX_ATTACHED_ITEMS + 1)]
        with self.assertRaises(exceptions.ValidationError):
            self._service().open({"content": "x", "attached_context": items})

    def test_text_length_cap(self):
        with self.assertRaises(exceptions.ValidationError):
            self._service().open(
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
            result = self._service().open(
                {
                    "content": "and the mobile funnel?",
                    "trace_id": "trace-2",
                    "attached_context": [{"type": "insight", "id": "abc"}],
                }
            )

        assert result is not None
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

    def test_in_progress_followup_clears_warm_flag(self):
        # A warm Run that receives its first human message is no longer speculative — the warm flag is
        # cleared so the warm-pool cap stops counting it (it becomes an active, AI-credit-governed Run).
        task, run = self._stub_task()
        run.status = TaskRun.Status.IN_PROGRESS
        run.state = {**(run.state or {}), "await_user_message": True}
        run.save(update_fields=["status", "state"])
        self._attach_task(task)

        with (
            patch(f"{ROUTING}.signal_task_followup_message"),
            patch.object(TaskRun, "append_log"),
        ):
            self._service().open({"content": "go", "attached_context": []})

        run.refresh_from_db()
        assert "await_user_message" not in run.state

    def test_in_progress_followup_raises_conflict_when_signal_fails(self):
        task, run = self._stub_task()
        run.status = TaskRun.Status.IN_PROGRESS
        run.save(update_fields=["status"])
        self._attach_task(task)

        with (
            patch(f"{ROUTING}.signal_task_followup_message", side_effect=RuntimeError("workflow gone")),
            patch.object(TaskRun, "append_log") as m_append,
        ):
            with self.assertRaises(Conflict):
                self._service().open({"content": "follow up", "attached_context": []})

        # The signal never reached the agent, so the turn is not logged — a retry stays clean
        # instead of leaving a duplicated user_message behind.
        m_append.assert_not_called()

    def test_in_progress_followup_succeeds_when_logging_fails(self):
        task, run = self._stub_task()
        run.status = TaskRun.Status.IN_PROGRESS
        run.save(update_fields=["status"])
        self._attach_task(task)

        with (
            patch(f"{ROUTING}.signal_task_followup_message") as m_signal,
            patch.object(TaskRun, "append_log", side_effect=RuntimeError("storage down")),
        ):
            result = self._service().open({"content": "follow up", "attached_context": []})

        # The agent already has the message; a log-append failure must not fail the request.
        assert result is not None
        m_signal.assert_called_once()
        assert result.run_id == str(run.id)

    def test_terminal_followup_creates_new_run_with_resume(self):
        task, run = self._stub_task()
        run.status = TaskRun.Status.COMPLETED
        run.state = {**(run.state or {}), "snapshot_external_id": "snap-9"}
        run.save(update_fields=["status", "state"])
        self._attach_task(task)

        with (
            patch(f"{ROUTING}.execute_task_processing_workflow") as m_workflow,
            patch.object(PromptService, "build", return_value=SYS_PROMPT),
        ):
            result = self._service().open({"content": "resume please", "trace_id": "trace-3"})

        assert result is not None
        assert result.task_id == str(task.id)
        assert result.just_created_run is True

        new_run = task.runs.order_by("-created_at").first()
        assert new_run is not None
        assert str(new_run.id) == result.run_id
        assert str(new_run.id) != str(run.id)
        assert new_run.state["resume_from_run_id"] == str(run.id)
        assert new_run.state["snapshot_external_id"] == "snap-9"
        assert new_run.state["interaction_origin"] == POSTHOG_AI_INTERACTION_ORIGIN
        assert new_run.state["systemPrompt"] == SYS_PROMPT
        assert new_run.state["initial_permission_mode"] == "auto"
        assert new_run.state["inactivity_timeout_seconds"] == SANDBOX_INACTIVITY_TIMEOUT_SECONDS
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
            patch.object(PromptService, "build", return_value=SYS_PROMPT),
            patch(f"{ROUTING}.object_storage.read", return_value=""),
        ):
            self._service().open(
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
            self._service().open({"content": "x"})

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
            patch.object(PromptService, "build", return_value=SYS_PROMPT),
        ):
            with self.assertRaises(Conflict):
                self._service().open({"content": "resume please"})

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
            patch.object(PromptService, "build", return_value=SYS_PROMPT),
        ):
            result = self._service().open({"content": "resume please"})

        assert result is not None
        new_run = task.runs.order_by("-created_at").first()
        assert new_run is not None
        assert str(new_run.id) == result.run_id
        assert new_run.state["resume_from_run_id"] != str(run.id)


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


class TestSandboxWarmViaOpen(APIBaseTest):
    """Warming via the message-less `open({})` — boot a Run that idles awaiting the first message."""

    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            agent_runtime=Conversation.AgentRuntime.SANDBOX,
        )

    def _service(self) -> SandboxSession:
        return SandboxSession(self.conversation, self.user)

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

    def test_warm_first_creates_warm_run_without_pending_message(self):
        with (
            patch(f"{WARM}.execute_task_processing_workflow") as m_workflow,
            patch(f"{WARM}.is_team_limited", return_value=False),
            patch.object(PromptService, "build", return_value=SYS_PROMPT),
            self.captureOnCommitCallbacks(execute=True),
        ):
            result = self._service().open({})

        assert result is not None
        self.conversation.refresh_from_db()
        assert self.conversation.task_id is not None
        task = self.conversation.task
        assert task is not None
        assert task.origin_product == Task.OriginProduct.POSTHOG_AI
        run = task.latest_run
        assert run is not None
        assert str(run.id) == result.run_id
        assert result.just_created_run is True
        assert run.state["interaction_origin"] == POSTHOG_AI_INTERACTION_ORIGIN
        assert run.state["systemPrompt"] == SYS_PROMPT
        assert run.state["await_user_message"] is True
        assert run.state["initial_permission_mode"] == "auto"
        assert run.state["inactivity_timeout_seconds"] == SANDBOX_INACTIVITY_TIMEOUT_SECONDS
        # No pending message / attached context: the session boots and idles awaiting input.
        assert "pending_user_message" not in run.state
        assert "attached_context" not in run.state
        m_workflow.assert_called_once()

    def test_warm_honors_initial_permission_mode(self):
        with (
            patch(f"{WARM}.execute_task_processing_workflow"),
            patch(f"{WARM}.is_team_limited", return_value=False),
            patch.object(PromptService, "build", return_value=SYS_PROMPT),
            self.captureOnCommitCallbacks(execute=True),
        ):
            result = self._service().open({"initial_permission_mode": "plan"})

        assert result is not None
        self.conversation.refresh_from_db()
        task = self.conversation.task
        assert task is not None
        run = task.latest_run
        assert run is not None
        assert run.state["initial_permission_mode"] == "plan"

    def test_warm_is_idempotent_when_run_already_in_progress(self):
        task, run = self._stub_task()
        run.status = TaskRun.Status.IN_PROGRESS
        run.save(update_fields=["status"])
        self.conversation.task = task
        self.conversation.save(update_fields=["task"])

        with (
            patch(f"{WARM}.execute_task_processing_workflow") as m_workflow,
            patch(f"{WARM}.is_team_limited", return_value=False),
            patch.object(PromptService, "build", return_value=SYS_PROMPT),
            self.captureOnCommitCallbacks(execute=True),
        ):
            result = self._service().open({})

        # The existing non-terminal Run is reused, not duplicated.
        assert result is not None
        assert result.run_id == str(run.id)
        assert result.just_created_run is False
        m_workflow.assert_not_called()
        assert task.runs.count() == 1

    def test_warm_rewarms_after_terminal_run(self):
        task, run = self._stub_task()
        run.status = TaskRun.Status.COMPLETED
        run.save(update_fields=["status"])
        self.conversation.task = task
        self.conversation.save(update_fields=["task"])

        with (
            patch(f"{WARM}.execute_task_processing_workflow") as m_workflow,
            patch(f"{WARM}.is_team_limited", return_value=False),
            patch.object(PromptService, "build", return_value=SYS_PROMPT),
            self.captureOnCommitCallbacks(execute=True),
        ):
            result = self._service().open({})

        assert result is not None
        new_run = task.latest_run
        assert new_run is not None
        assert str(new_run.id) == result.run_id
        assert new_run.id != run.id
        assert new_run.state["await_user_message"] is True
        assert new_run.state["systemPrompt"] == SYS_PROMPT
        assert new_run.state["resume_from_run_id"] == str(run.id)
        m_workflow.assert_called_once()

    def test_warm_over_quota_raises_and_creates_no_task(self):
        # The AI-credit gate lives behind the tasks warming facade; an over-quota warm must not leave a runless Task.
        with (
            patch(f"{WARM}.is_team_limited", return_value=True),
            patch.object(PromptService, "build", return_value=SYS_PROMPT),
            self.assertRaises(QuotaLimitExceeded),
        ):
            self._service().open({})

        self.conversation.refresh_from_db()
        assert self.conversation.task_id is None

    def _warm_run(self, *, created_by=None) -> TaskRun:
        """A non-terminal warm Run (awaiting its first message) that counts toward the warm-pool cap."""
        task = Task.objects.create(
            team=self.team,
            title="",
            description="",
            origin_product=Task.OriginProduct.POSTHOG_AI,
            created_by=created_by or self.user,
        )
        return task.create_run(mode="interactive", extra_state={"await_user_message": True})  # QUEUED

    def _fill_warm_pool(self, *, created_by=None) -> None:
        for _ in range(100):
            if warm_facade.warm_pool_at_capacity(Task.OriginProduct.POSTHOG_AI, self.team.id, self.user.id):
                return
            self._warm_run(created_by=created_by)
        self.fail("Warm pool did not reach capacity")

    def test_warm_skips_when_user_at_capacity(self):
        self._fill_warm_pool()

        with (
            patch(f"{WARM}.execute_task_processing_workflow") as m_workflow,
            patch(f"{WARM}.is_team_limited", return_value=False),
            patch.object(PromptService, "build", return_value=SYS_PROMPT),
            self.captureOnCommitCallbacks(execute=True),
        ):
            result = self._service().open({})

        # Pool full and nothing provisioned — the warm handle is None.
        assert result is None
        m_workflow.assert_not_called()
        # The cap is pre-checked before Task creation, so a brand-new conversation gets no runless Task.
        self.conversation.refresh_from_db()
        assert self.conversation.task_id is None

    def test_warm_skips_when_org_at_capacity(self):
        other = self._create_user("warmer@posthog.com")
        self._fill_warm_pool(created_by=other)

        with (
            patch(f"{WARM}.execute_task_processing_workflow") as m_workflow,
            patch(f"{WARM}.is_team_limited", return_value=False),
            patch.object(PromptService, "build", return_value=SYS_PROMPT),
            self.captureOnCommitCallbacks(execute=True),
        ):
            result = self._service().open({})

        assert result is None
        m_workflow.assert_not_called()

    def test_warm_ignores_terminal_runs_for_capacity(self):
        # Terminal runs don't hold a sandbox, so they must not count toward the cap.
        for _ in range(20):
            run = self._warm_run()
            run.status = TaskRun.Status.COMPLETED
            run.save(update_fields=["status"])

        with (
            patch(f"{WARM}.execute_task_processing_workflow") as m_workflow,
            patch(f"{WARM}.is_team_limited", return_value=False),
            patch.object(PromptService, "build", return_value=SYS_PROMPT),
            self.captureOnCommitCallbacks(execute=True),
        ):
            result = self._service().open({})

        assert result is not None
        m_workflow.assert_called_once()
        self.conversation.refresh_from_db()
        assert self.conversation.task_id is not None

    def test_warm_ignores_activated_runs_for_capacity(self):
        # Activated Runs (await_user_message cleared) are active, not warm, so they don't count toward
        # the warm cap — the warm and AI-credit budgets are disjoint.
        for _ in range(20):
            run = self._warm_run()
            TaskRun.update_state_atomic(run.id, remove_keys=["await_user_message"])

        with (
            patch(f"{WARM}.execute_task_processing_workflow") as m_workflow,
            patch(f"{WARM}.is_team_limited", return_value=False),
            patch.object(PromptService, "build", return_value=SYS_PROMPT),
            self.captureOnCommitCallbacks(execute=True),
        ):
            result = self._service().open({})

        assert result is not None
        m_workflow.assert_called_once()

    def test_warm_first_serializes_on_conversation_lock(self):
        # The first warm runs under the conversation row lock, so a second concurrent warm can't
        # create a duplicate Task on a task-less conversation.
        with (
            patch(f"{WARM}.execute_task_processing_workflow"),
            patch(f"{WARM}.is_team_limited", return_value=False),
            patch.object(PromptService, "build", return_value=SYS_PROMPT),
            patch(f"{ROUTING}.lock_conversation_for_followup", wraps=lock_conversation_for_followup) as m_lock,
            self.captureOnCommitCallbacks(execute=True),
        ):
            self._service().open({})

        m_lock.assert_called_once_with(str(self.conversation.id), self.team.pk)


class TestAwaitUserMessageStoredKey:
    """Guards the warm-pool cap, which filters on `state__await_user_message` directly."""

    def test_await_user_message_is_stored_under_its_literal_key(self):
        # The cap query (products/tasks/backend/logic/services/warm.py) filters on the JSON key literally.
        # Adding an alias to this field would change the stored key and silently open the cap.
        dumped = PostHogAIRunState(await_user_message=True).model_dump(by_alias=True, exclude_unset=True)
        assert dumped == {"await_user_message": True}


class TestSandboxFirstMessageConversion(APIBaseTest):
    """Converting an idle LangGraph conversation on its first sandbox message.

    Conversion is just: flip the runtime + link the Task on the normal first-message path, with the
    legacy window prepended to the first prompt. No ACP seeding, no synthetic historical run.
    """

    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            title="Why did checkout drop?",
            agent_runtime=Conversation.AgentRuntime.LANGGRAPH,
            status=Conversation.Status.IDLE,
        )

    def _block(self) -> str:
        return "<posthog_context>This session was resumed from the legacy implementation.\nUser: hi</posthog_context>"

    def _open(self, *, resumed_context=None, convert_to_acp=False, content="continue here"):
        with patch(f"{ROUTING}.execute_task_processing_workflow") as m_workflow:
            result = SandboxSession(self.conversation, self.user).open(
                {"content": content, "trace_id": "t"},
                resumed_context=resumed_context,
                convert_to_acp=convert_to_acp,
            )
        return result, m_workflow

    def test_first_message_conversion_flips_runtime_and_links_task(self):
        result, m_workflow = self._open(resumed_context=self._block(), convert_to_acp=True)

        self.conversation.refresh_from_db()
        assert self.conversation.agent_runtime == Conversation.AgentRuntime.SANDBOX
        assert self.conversation.task_id is not None

        task = self.conversation.task
        assert task is not None
        assert task.origin_product == Task.OriginProduct.POSTHOG_AI
        # The live first run, not a synthetic terminal one.
        assert task.runs.count() == 1
        first_run = task.runs.first()
        assert first_run is not None
        assert first_run.status != TaskRun.Status.COMPLETED
        assert result is not None
        assert result.just_created_run is True
        m_workflow.assert_called_once()

    def test_first_message_conversion_does_not_seed_s3_log(self):
        with patch.object(TaskRun, "append_log") as m_append:
            self._open(resumed_context=self._block(), convert_to_acp=True)
        m_append.assert_not_called()

    def test_first_message_conversion_prepends_window_context(self):
        self._open(resumed_context=self._block(), convert_to_acp=True)

        self.conversation.refresh_from_db()
        task = self.conversation.task
        assert task is not None
        run = task.runs.first()
        assert run is not None
        pending = run.state["pending_user_message"]
        assert pending.startswith(self._block())
        assert pending.endswith("continue here")

    def test_first_message_conversion_idempotent_under_lock(self):
        # Simulate a concurrent winner: the DB row is linked to a Task after this request's entry
        # check but before it takes the lock. The under-lock re-check must surface a Conflict.
        other_task = Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=Task.OriginProduct.POSTHOG_AI,
            created_by=self.user,
        )
        Conversation.objects.filter(id=self.conversation.id).update(task=other_task)

        with self.assertRaises(Conflict):
            self._open(resumed_context=self._block(), convert_to_acp=True)

        self.conversation.refresh_from_db()
        assert self.conversation.task_id == other_task.id

    def test_first_message_conversion_reverts_on_workflow_start_failure(self):
        with patch(f"{ROUTING}.execute_task_processing_workflow", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                SandboxSession(self.conversation, self.user).open(
                    {"content": "continue here", "trace_id": "t"},
                    resumed_context=self._block(),
                    convert_to_acp=True,
                )

        # A failed start leaves a clean idle LangGraph conversation the user can retry.
        self.conversation.refresh_from_db()
        assert self.conversation.agent_runtime == Conversation.AgentRuntime.LANGGRAPH
        assert self.conversation.task_id is None

    def test_born_sandbox_first_message_does_not_flip(self):
        self.conversation.agent_runtime = Conversation.AgentRuntime.SANDBOX
        self.conversation.save(update_fields=["agent_runtime"])

        result, m_workflow = self._open()

        self.conversation.refresh_from_db()
        assert self.conversation.agent_runtime == Conversation.AgentRuntime.SANDBOX
        assert self.conversation.task_id is not None
        assert result is not None
        assert result.just_created_run is True
        m_workflow.assert_called_once()

    def test_born_sandbox_first_message_has_no_resumed_context(self):
        self.conversation.agent_runtime = Conversation.AgentRuntime.SANDBOX
        self.conversation.save(update_fields=["agent_runtime"])

        self._open(content="just this please")

        self.conversation.refresh_from_db()
        task = self.conversation.task
        assert task is not None
        run = task.runs.first()
        assert run is not None
        assert run.state["pending_user_message"] == "just this please"
