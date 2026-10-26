from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models.personal_api_key import PersonalAPIKey

from products.posthog_ai.backend.models import AgentOperation
from products.posthog_ai.backend.services.agent_operations.delegation import granted_scopes
from products.posthog_ai.backend.services.agent_operations.progress import summarize_run_log
from products.posthog_ai.backend.services.agent_operations.result_schema import AGENT_RESULT_SCHEMA
from products.posthog_ai.backend.services.system_prompt.service import PromptService
from products.tasks.backend.models import Task, TaskRun

ROUTING = "products.posthog_ai.backend.message_routing"
VIEW = "products.posthog_ai.backend.presentation.agent_operations"
SERVICE = "products.posthog_ai.backend.services.agent_operations.service"
SYS_PROMPT = {"type": "preset", "preset": "claude_code", "append": "SYS"}


def _update(update: dict) -> dict:
    return {"type": "notification", "notification": {"method": "session/update", "params": {"update": update}}}


class TestDelegationAndProgress(SimpleTestCase):
    @parameterized.expand(
        [
            ("read_key_cannot_write_flags", ["feature_flag:read"], "feature_flag:write", False),
            ("write_key_can_write_flags", ["feature_flag:write"], "feature_flag:write", True),
            ("write_covers_read", ["feature_flag:write"], "feature_flag:read", True),
            ("unrelated_scope_not_granted", ["insight:write"], "feature_flag:read", False),
            ("wildcard_key_gets_preset", ["*"], "feature_flag:write", True),
        ]
    )
    def test_grant_never_exceeds_the_caller(self, _name, held, scope, expected):
        assert (scope in granted_scopes(held)) is expected

    def test_progress_reads_plan_steps_and_clears_answered_permission(self):
        permission = {
            "type": "notification",
            "notification": {
                "method": "_posthog/permission_request",
                "params": {
                    "requestId": "req-1",
                    "toolCall": {"toolCallId": "call-2", "title": "Call another project"},
                    "options": [{"optionId": "allow", "kind": "allow_once", "name": "Allow"}],
                },
            },
        }
        entries = [
            _update({"sessionUpdate": "plan", "entries": [{"content": "Count weekly signups", "status": "completed"}]}),
            _update(
                {
                    "sessionUpdate": "tool_call",
                    "toolCallId": "call-1",
                    "title": "Bash",
                    "kind": "execute",
                    "rawInput": {"command": "ls", "description": "List the files"},
                    "_meta": {"claudeCode": {"toolName": "Bash"}},
                }
            ),
            permission,
        ]
        pending = summarize_run_log(entries)
        assert pending.plan == [{"content": "Count weekly signups", "status": "completed"}]
        assert pending.steps == ["List the files"]
        assert pending.pending_permission is not None and pending.pending_permission.request_id == "req-1"

        answered = summarize_run_log(
            [*entries, _update({"sessionUpdate": "tool_call_update", "toolCallId": "call-2", "status": "completed"})]
        )
        assert answered.pending_permission is None


class TestAgentOperationsAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        patch(f"{VIEW}.feature_enabled_or_false", return_value=True).start()
        patch(f"{VIEW}.is_team_limited", return_value=False).start()
        patch.object(PromptService, "build", return_value=SYS_PROMPT).start()
        patch(f"{SERVICE}.tasks_facade.read_task_run_logs", return_value=None).start()
        self.dispatch = patch(f"{ROUTING}.dispatch_task_processing_workflow").start()
        self.addCleanup(patch.stopall)
        self.url = f"/api/projects/{self.team.id}/agent_operations/"

    def _start(self, *, client_request_id: str = "req-1", goal: str = "Why did signups drop?", key: str | None = None):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {key}"} if key else {}
        return self.client.post(
            self.url, {"goal": goal, "client_request_id": client_request_id}, format="json", **headers
        )

    def _run(self, operation_id: str) -> TaskRun:
        operation = AgentOperation.objects.for_team(self.team.id).get(id=operation_id)
        return TaskRun.objects.get(id=operation.run_id)

    def test_start_narrows_the_sandbox_grant_to_the_key(self):
        key = self.create_personal_api_key_with_scopes(["conversation:write", "feature_flag:read", "insight:write"])

        response = self._start(key=key)

        assert response.status_code == 201, response.json()
        scopes = self.dispatch.call_args.kwargs["posthog_mcp_scopes"]
        assert "feature_flag:write" not in scopes
        assert {"feature_flag:read", "insight:write"} <= set(scopes)
        task = Task.objects.get(id=response.json()["task_id"])
        assert task.json_schema == AGENT_RESULT_SCHEMA
        assert task.client_provenance == "agent_mcp"
        assert response.json()["project"] == {"id": self.team.id, "name": self.team.name}

    def test_retry_with_same_request_id_returns_the_same_operation(self):
        first = self._start()
        retry = self._start()
        conflict = self._start(goal="A different goal")

        assert (first.status_code, retry.status_code, conflict.status_code) == (201, 200, 409)
        assert retry.json()["id"] == first.json()["id"]
        assert conflict.json()["code"] == "client_request_id_reused"
        assert self.dispatch.call_count == 1

    def test_active_operation_limit(self):
        for index in range(3):
            assert self._start(client_request_id=f"req-{index}").status_code == 201

        response = self._start(client_request_id="req-3")

        assert response.status_code == 429
        assert response.json()["code"] == "too_many_operations"

    @parameterized.expand(
        [
            (
                "complete",
                {
                    "status": "complete",
                    "answer": "Signups fell 12%.",
                    "question": "",
                    "assumptions": [],
                    "evidence": [],
                    "artifacts": [],
                    "follow_ups": [],
                },
                TaskRun.Status.COMPLETED,
                "succeeded",
                None,
            ),
            (
                "needs_input",
                {
                    "status": "needs_input",
                    "answer": "",
                    "question": "Which plan?",
                    "assumptions": [],
                    "evidence": [],
                    "artifacts": [],
                    "follow_ups": [],
                },
                TaskRun.Status.COMPLETED,
                "needs_input",
                "question",
            ),
            ("completed_without_result", None, TaskRun.Status.COMPLETED, "failed", "no_result"),
            ("still_running", None, TaskRun.Status.IN_PROGRESS, "running", None),
        ]
    )
    def test_status_follows_the_run_and_its_result(self, _name, output, run_status, state, reason):
        operation_id = self._start().json()["id"]
        run = self._run(operation_id)
        run.output = output
        run.status = run_status
        run.save()

        body = self.client.get(f"{self.url}{operation_id}/").json()

        assert (body["state"], body["state_reason"]) == (state, reason)
        if output is not None:
            assert body["result"]["answer"] == output["answer"]
        if state == "needs_input":
            assert body["question"] == "Which plan?"

    def test_deadline_expires_and_stops_the_run(self):
        operation_id = self._start().json()["id"]
        AgentOperation.objects.for_team(self.team.id).filter(id=operation_id).update(
            deadline_at=timezone.now() - timedelta(minutes=1)
        )

        with patch(f"{SERVICE}.tasks_cancellation.cancel_task_run", return_value=("cancelled", None)) as cancel:
            body = self.client.get(f"{self.url}{operation_id}/").json()

        assert (body["state"], body["state_reason"]) == ("expired", "deadline")
        cancel.assert_called_once()

    def test_revoking_the_key_stops_the_operation(self):
        key = self.create_personal_api_key_with_scopes(["conversation:write"])
        operation_id = self._start(key=key).json()["id"]

        with (
            patch(f"{SERVICE}.tasks_cancellation.cancel_task_run", return_value=("cancelled", None)) as cancel,
            self.captureOnCommitCallbacks(execute=True),
        ):
            PersonalAPIKey.objects.filter(user=self.user).delete()

        operation = AgentOperation.objects.for_team(self.team.id).get(id=operation_id)
        assert (operation.state, operation.state_reason) == ("failed", "credential_revoked")
        cancel.assert_called_once()

    def test_reply_is_delivered_once_per_request_id(self):
        operation_id = self._start().json()["id"]
        run = self._run(operation_id)
        run.output = {
            "status": "needs_input",
            "answer": "",
            "question": "Which plan?",
            "assumptions": [],
            "evidence": [],
            "artifacts": [],
            "follow_ups": [],
        }
        run.status = TaskRun.Status.COMPLETED
        run.save()

        reply_url = f"{self.url}{operation_id}/reply/"
        with patch(
            f"{SERVICE}.SandboxSession.open",
            return_value=MagicMock(run_id=str(run.id), task_id=str(run.task_id), just_created_run=True),
        ) as open_:
            first = self.client.post(reply_url, {"message": "The pro plan", "client_request_id": "r-1"}, format="json")
            retry = self.client.post(reply_url, {"message": "The pro plan", "client_request_id": "r-1"}, format="json")

        assert (first.status_code, retry.status_code) == (200, 200)
        assert open_.call_count == 1
