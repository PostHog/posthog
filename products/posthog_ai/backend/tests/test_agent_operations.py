import json
import uuid
from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.oauth import OAuthApplication, OAuthRefreshToken, revoke_oauth_session, revoke_oauth_token_family
from posthog.models.personal_api_key import PersonalAPIKey

from products.posthog_ai.backend.models import AgentOperation
from products.posthog_ai.backend.services.agent_operations.delegation import granted_scopes
from products.posthog_ai.backend.services.agent_operations.progress import summarize_run_log
from products.posthog_ai.backend.services.agent_operations.result_schema import AGENT_RESULT_SCHEMA
from products.posthog_ai.backend.services.agent_operations.service import reconcile_unwatched_operations
from products.posthog_ai.backend.services.system_prompt.service import PromptService
from products.tasks.backend.models import Task, TaskRun

ROUTING = "products.posthog_ai.backend.message_routing"
VIEW = "products.posthog_ai.backend.presentation.agent_operations"
SERVICE = "products.posthog_ai.backend.services.agent_operations.service"
SYS_PROMPT = {"type": "preset", "preset": "claude_code", "append": "SYS"}


def _update(update: dict) -> dict:
    return {"type": "notification", "notification": {"method": "session/update", "params": {"update": update}}}


def _permission(tool_call: dict) -> dict:
    return {
        "type": "notification",
        "notification": {
            "method": "_posthog/permission_request",
            "params": {
                "requestId": "req-1",
                "toolCall": tool_call,
                "options": [
                    {"optionId": "allow", "kind": "allow_once", "name": "Yes"},
                    {"optionId": "allow_always", "kind": "allow_always", "name": "Yes, always allow"},
                    {"optionId": "reject", "kind": "reject_once", "name": "No"},
                ],
            },
        },
    }


def _exec_call(command: str) -> dict:
    return {
        "toolCallId": "call-2",
        "title": "The agent wants to run `execute-sql` on PostHog",
        "kind": "other",
        "rawInput": {"command": command, "toolName": "mcp__posthog__exec"},
        "_meta": {"claudeCode": {"toolName": "mcp__posthog__exec"}},
    }


SQL_COMMAND = 'call execute-sql {"query": "SELECT count() FROM events"}'
LONG_SQL_COMMAND = f'call execute-sql {{"query": "SELECT {"x, " * 300}1"}}'
SUMMARY_TOOL_CALL = {
    "toolCallId": "call-3",
    "title": "task_summary_update",
    "kind": "other",
    "rawInput": {"summary": "Counting signups", "toolName": "mcp__posthog-code-tools__task_summary_update"},
    "_meta": {"claudeCode": {"toolName": "mcp__posthog-code-tools__task_summary_update"}},
}
BASH_STEP = _update(
    {
        "sessionUpdate": "tool_call",
        "toolCallId": "call-1",
        "title": "Bash",
        "kind": "execute",
        "rawInput": {"command": "ls", "description": "List the files"},
        "_meta": {"claudeCode": {"toolName": "Bash"}},
    }
)


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

    @parameterized.expand(
        [
            (
                "tool_call_finished",
                _update({"sessionUpdate": "tool_call_update", "toolCallId": "call-2", "status": "completed"}),
            ),
            (
                "permission_resolved",
                {
                    "type": "notification",
                    "notification": {
                        "method": "_posthog/permission_resolved",
                        "params": {"requestId": "req-1", "toolCallId": "call-2", "optionId": "allow"},
                    },
                },
            ),
        ]
    )
    def test_progress_reads_plan_steps_and_clears_answered_permission(self, _name, answer):
        entries = [
            _update({"sessionUpdate": "plan", "entries": [{"content": "Count weekly signups", "status": "completed"}]}),
            BASH_STEP,
            _permission({"toolCallId": "call-2", "title": "Call another project"}),
        ]
        pending = summarize_run_log(entries)
        assert pending.plan == [{"content": "Count weekly signups", "status": "completed"}]
        assert pending.steps == ["List the files"]
        assert pending.pending_permission is not None and pending.pending_permission.request_id == "req-1"

        assert summarize_run_log([*entries, answer]).pending_permission is None

    @parameterized.expand(
        [
            ("posthog_exec_shows_the_command", _exec_call(SQL_COMMAND), "Execute SQL query", SQL_COMMAND),
            ("long_command_is_cut", _exec_call(LONG_SQL_COMMAND), "Execute SQL query", LONG_SQL_COMMAND[:599] + "…"),
            (
                "bash_uses_its_description",
                {
                    "toolCallId": "call-2",
                    "title": "rm -rf build",
                    "kind": "execute",
                    "rawInput": {
                        "command": "rm -rf build",
                        "description": "Remove the build folder",
                        "toolName": "Bash",
                    },
                },
                "Remove the build folder",
                None,
            ),
            ("hidden_tool_keeps_its_title", SUMMARY_TOOL_CALL, "task_summary_update", None),
        ]
    )
    def test_permission_request_uses_the_step_label(self, _name, tool_call, title, detail):
        pending = summarize_run_log([_permission(tool_call)]).pending_permission

        assert pending is not None
        assert (pending.title, pending.detail) == (title, detail)


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

    def _start(
        self,
        *,
        client_request_id: str = "req-1",
        goal: str = "Why did signups drop?",
        key: str | None = None,
        approvals: str | None = None,
    ):
        headers: dict[str, Any] = {"HTTP_AUTHORIZATION": f"Bearer {key}"} if key else {}
        body = {"goal": goal, "client_request_id": client_request_id}
        if approvals:
            body["approvals"] = approvals
        return self.client.post(self.url, body, format="json", **headers)

    def _run(self, operation_id: str) -> TaskRun:
        operation = AgentOperation.objects.for_team(self.team.id).get(id=operation_id)
        assert operation.run_id is not None
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

    def test_a_repository_run_gets_read_only_github_access_at_the_pinned_commit(self):
        commit = "b" * 40
        Integration.objects.create(team=self.team, kind="github", integration_id="12345", config={})
        with patch(f"{SERVICE}.repo_selection.resolve_repository_commit", return_value=commit):
            response = self.client.post(
                self.url,
                {"goal": "Where is signup tracked?", "client_request_id": "req-1", "repository": "acme/web"},
                format="json",
            )

        assert response.status_code == 201, response.json()
        run = TaskRun.objects.get(id=response.json()["run_id"])
        assert (run.branch, run.state.get("github_read_access")) == (commit, True)

    @parameterized.expand([("no_ui_client", None, "bypassPermissions"), ("ui_client", "client", "auto")])
    def test_only_a_client_with_approval_ui_gets_approval_prompts(self, _name, approvals, permission_mode):
        response = self._start(approvals=approvals)

        assert response.status_code == 201, response.json()
        assert TaskRun.objects.get(id=response.json()["run_id"]).state["initial_permission_mode"] == permission_mode

    @parameterized.expand(
        [("allow_all", "allow all", "always"), ("allow", "allow", "once"), ("deny", "deny", "reject")]
    )
    def test_approval_reply_picks_the_matching_option(self, _name, message, option_id):
        operation_id = self._start(approvals="client").json()["id"]
        run = self._run(operation_id)
        run.status = TaskRun.Status.IN_PROGRESS
        run.save()
        AgentOperation.objects.for_team(self.team.id).filter(id=operation_id).update(
            state="needs_input",
            state_reason="approval_required",
            pending_permission_request={
                "request_id": "perm-1",
                "title": "Run SQL",
                "options": [
                    {"option_id": "once", "kind": "allow_once", "name": "Allow"},
                    {"option_id": "always", "kind": "allow_always", "name": "Always allow"},
                    {"option_id": "reject", "kind": "reject_once", "name": "Deny"},
                ],
            },
        )

        with (
            patch(f"{SERVICE}.tasks_facade.send_permission_response", return_value=True) as send,
            patch(f"{SERVICE}.SandboxSession.open") as open_,
        ):
            response = self.client.post(
                f"{self.url}{operation_id}/reply/", {"message": message, "client_request_id": "r-1"}, format="json"
            )

        assert response.status_code == 200, response.json()
        assert send.call_args.kwargs["option_id"] == option_id
        open_.assert_not_called()

    @parameterized.expand(
        [
            ("harness_tool_is_auto_approved", SUMMARY_TOOL_CALL, "running", None, None, "allow_always"),
            (
                "posthog_call_waits_for_the_user",
                _exec_call(SQL_COMMAND),
                "needs_input",
                "Execute SQL query",
                SQL_COMMAND,
                None,
            ),
        ]
    )
    def test_permission_request_in_the_log(self, _name, tool_call, state, title, detail, sent_option):
        operation_id = self._start(approvals="client").json()["id"]
        run = self._run(operation_id)
        run.status = TaskRun.Status.IN_PROGRESS
        run.save()
        log = "\n".join(json.dumps(entry) for entry in (BASH_STEP, _permission(tool_call)))

        with (
            patch(f"{SERVICE}.tasks_facade.read_task_run_logs", return_value=log),
            patch(f"{SERVICE}.tasks_facade.send_permission_response", return_value=True) as send,
        ):
            body = self.client.get(f"{self.url}{operation_id}/").json()

        approval = body["approval"] or {}
        assert (body["state"], approval.get("title"), approval.get("detail"), body["steps_total"]) == (
            state,
            title,
            detail,
            1,
        )
        assert (send.call_args.kwargs["option_id"] if send.called else None) == sent_option

    def test_an_answered_approval_stays_answered_while_the_log_catches_up(self):
        operation_id = self._start(approvals="client").json()["id"]
        run = self._run(operation_id)
        run.status = TaskRun.Status.IN_PROGRESS
        run.save()
        log = "\n".join(json.dumps(entry) for entry in (BASH_STEP, _permission(_exec_call(SQL_COMMAND))))

        with (
            patch(f"{SERVICE}.tasks_facade.read_task_run_logs", return_value=log),
            patch(f"{SERVICE}.tasks_facade.send_permission_response", return_value=True) as send,
        ):
            waiting = self.client.get(f"{self.url}{operation_id}/").json()
            answered = self.client.post(
                f"{self.url}{operation_id}/reply/", {"message": "allow", "client_request_id": "r-1"}, format="json"
            ).json()
            later = self.client.get(f"{self.url}{operation_id}/").json()

        assert [(body["state"], body["approval"] is None) for body in (waiting, answered, later)] == [
            ("needs_input", False),
            ("running", True),
            ("running", True),
        ]
        assert send.call_count == 1

    @parameterized.expand(
        [
            ("late_allow", "allow", 409, "no_pending_approval", 0),
            ("late_allow_all", "Allow all!", 409, "no_pending_approval", 0),
            ("late_deny", "deny.", 409, "no_pending_approval", 0),
            ("late_approved", "Approved", 409, "no_pending_approval", 0),
            ("steering_message", "Look at mobile signups too", 200, None, 1),
        ]
    )
    def test_approval_answer_with_no_pending_approval_is_not_sent_as_chat(self, _name, message, status, code, sends):
        operation_id = self._start(approvals="client").json()["id"]
        run = self._run(operation_id)
        run.status = TaskRun.Status.IN_PROGRESS
        run.save()

        with patch(
            f"{SERVICE}.SandboxSession.open",
            return_value=MagicMock(run_id=str(run.id), task_id=str(run.task_id), just_created_run=False),
        ) as open_:
            response = self.client.post(
                f"{self.url}{operation_id}/reply/", {"message": message, "client_request_id": "r-1"}, format="json"
            )

        assert (response.status_code, response.json().get("code"), open_.call_count) == (status, code, sends)

    def test_retry_with_same_request_id_returns_the_same_operation(self):
        first = self._start()
        retry = self._start()
        conflict = self._start(goal="A different goal")

        assert (first.status_code, retry.status_code, conflict.status_code) == (201, 200, 409)
        assert retry.json()["id"] == first.json()["id"]
        assert conflict.json()["code"] == "client_request_id_reused"
        assert self.dispatch.call_count == 1

    @parameterized.expand(
        [
            ("three_working_runs", None, TaskRun.Status.IN_PROGRESS, None, 409),
            ("one_run_finished_unread", {"status": "complete", "answer": "Done."}, TaskRun.Status.COMPLETED, None, 201),
            (
                "one_run_waits_on_a_question",
                {"status": "needs_input", "answer": "", "question": "Which plan?"},
                TaskRun.Status.COMPLETED,
                None,
                201,
            ),
            (
                "one_run_waits_on_an_approval",
                None,
                TaskRun.Status.IN_PROGRESS,
                {"request_id": "perm-1", "title": "Run SQL", "detail": None, "options": []},
                409,
            ),
        ]
    )
    def test_only_runs_that_hold_a_sandbox_count_toward_the_active_limit(
        self, _name, output, run_status, pending_approval, expected_status
    ):
        ids = [self._start(client_request_id=f"req-{index}").json()["id"] for index in range(3)]
        for operation_id in ids:
            run = self._run(operation_id)
            run.status = TaskRun.Status.IN_PROGRESS
            run.save()
        changed = self._run(ids[0])
        changed.output = output
        changed.status = run_status
        changed.save()
        if pending_approval:
            AgentOperation.objects.for_team(self.team.id).filter(id=ids[0]).update(
                state="needs_input", state_reason="approval_required", pending_permission_request=pending_approval
            )

        response = self._start(client_request_id="req-3")

        assert response.status_code == expected_status, response.json()
        if expected_status == 409:
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
        AgentOperation.objects.for_team(self.team.id).filter(id=operation_id).update(
            progress_snapshot={"plan": [], "steps_count": 3}
        )

        body = self.client.get(f"{self.url}{operation_id}/").json()

        assert (body["state"], body["state_reason"], body["steps_total"]) == (state, reason, 3)
        if output is not None:
            assert body["result"]["answer"] == output["answer"]
        if state == "needs_input":
            assert body["question"] == "Which plan?"

    def test_ai_rate_limits_apply_to_starting_work_and_not_to_status_reads(self):
        operation_id = self._start().json()["id"]

        reads = [self.client.get(f"{self.url}{operation_id}/").status_code for _ in range(15)]
        with patch(f"{SERVICE}.MAX_ACTIVE_OPERATIONS_PER_USER", 20):
            starts = [self._start(client_request_id=f"req-{i}").status_code for i in range(2, 12)]

        assert reads == [200] * 15
        assert starts == [201] * 9 + [429]

    @parameterized.expand(
        [
            ("stop_sent", [("accepted", None)], "expired", 1),
            ("stop_retried_by_the_sweep", [("unavailable", None), ("accepted", None)], "cancelling", 2),
        ]
    )
    def test_deadline_expires_once_the_run_stop_is_sent(self, _name, outcomes, state_after_read, stop_calls):
        operation_id = self._start().json()["id"]
        AgentOperation.objects.for_team(self.team.id).filter(id=operation_id).update(
            deadline_at=timezone.now() - timedelta(minutes=1)
        )

        with patch(f"{SERVICE}.tasks_cancellation.cancel_task_run", side_effect=outcomes) as cancel:
            body = self.client.get(f"{self.url}{operation_id}/").json()
            reconcile_unwatched_operations()

        operation = AgentOperation.objects.for_team(self.team.id).get(id=operation_id)
        assert (body["state"], body["state_reason"]) == (state_after_read, "deadline")
        assert (operation.state, operation.state_reason, cancel.call_count) == ("expired", "deadline", stop_calls)

    def test_cancel_during_the_first_dispatch_stops_the_new_run(self):
        run = TaskRun.objects.create(team=self.team, task=Task.objects.create(team=self.team, title="t"))

        def open_and_cancel(*_args, **_kwargs):
            operation = AgentOperation.objects.for_team(self.team.id).get(client_request_id="req-1")
            self.client.post(f"{self.url}{operation.id}/cancel/")
            return MagicMock(run_id=str(run.id), task_id=str(run.task_id), just_created_run=True)

        with (
            patch(f"{SERVICE}.SandboxSession.open", side_effect=open_and_cancel),
            patch(f"{SERVICE}.tasks_cancellation.cancel_task_run", return_value=("accepted", None)) as cancel,
        ):
            body = self._start().json()

        assert (body["state"], body["run_id"]) == ("cancelling", str(run.id))
        assert str(cancel.call_args.args[0]) == str(run.id)

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

    @parameterized.expand(
        [
            ("scope_removed", {"scopes": ["conversation:write"]}),
            ("scoped_to_another_project", {"scoped_teams": [999999]}),
        ]
    )
    def test_narrowing_the_key_stops_the_operation(self, _name, change):
        key = self.create_personal_api_key_with_scopes(["conversation:write", "insight:write"])
        operation_id = self._start(key=key).json()["id"]
        PersonalAPIKey.objects.filter(user=self.user).update(**change)

        with patch(f"{SERVICE}.tasks_cancellation.cancel_task_run", return_value=("accepted", None)) as cancel:
            body = self.client.get(f"{self.url}{operation_id}/").json()

        assert (body["state"], body["state_reason"]) == ("failed", "credential_revoked")
        cancel.assert_called_once()

    @parameterized.expand(
        [
            ("family_revoked", lambda token: revoke_oauth_token_family(token)),
            ("app_disconnected", lambda token: revoke_oauth_session(refresh_token=token)),
        ]
    )
    def test_bulk_oauth_revocation_stops_the_operation(self, _name, revoke):
        application = OAuthApplication.objects.create(
            name="Agent client",
            client_id="agent-client",
            client_secret="agent-secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            user=self.user,
            hash_client_secret=True,
            algorithm="RS256",
        )
        family = uuid.uuid4()
        token = OAuthRefreshToken.objects.create(
            user=self.user, application=application, token="refresh-1", token_family=family
        )
        operation_id = self._start().json()["id"]
        AgentOperation.objects.for_team(self.team.id).filter(id=operation_id).update(
            parent_credential_kind=AgentOperation.ParentCredentialKind.OAUTH_TOKEN_FAMILY,
            parent_credential_ref=str(family),
        )

        with (
            patch(f"{SERVICE}.tasks_cancellation.cancel_task_run", return_value=("accepted", None)) as cancel,
            self.captureOnCommitCallbacks(execute=True),
        ):
            revoke(token)

        operation = AgentOperation.objects.for_team(self.team.id).get(id=operation_id)
        assert (operation.state, operation.state_reason) == ("failed", "credential_revoked")
        cancel.assert_called_once()

    def test_a_narrower_key_cannot_steer_the_operation(self):
        broad = self.create_personal_api_key_with_scopes(["conversation:write", "insight:write"])
        narrow = self.create_personal_api_key_with_scopes(["conversation:write"])
        operation_id = self._start(key=broad).json()["id"]

        with patch(f"{SERVICE}.SandboxSession.open") as open_:
            response = self.client.post(
                f"{self.url}{operation_id}/reply/",
                {"message": "Also delete the old insights", "client_request_id": "r-1"},
                format="json",
                HTTP_AUTHORIZATION=f"Bearer {narrow}",
            )

        assert (response.status_code, response.json()["code"]) == (403, "insufficient_scope")
        open_.assert_not_called()

    def test_starting_work_needs_ai_data_processing_approval(self):
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        response = self._start()

        assert response.status_code == 403
        self.dispatch.assert_not_called()

    @parameterized.expand([("free_text", "The pro plan"), ("approval_word", "allow")])
    def test_reply_to_a_question_is_delivered_once_per_request_id(self, _name, message):
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
            first = self.client.post(reply_url, {"message": message, "client_request_id": "r-1"}, format="json")
            retry = self.client.post(reply_url, {"message": message, "client_request_id": "r-1"}, format="json")

        assert (first.status_code, retry.status_code) == (200, 200)
        assert open_.call_count == 1
