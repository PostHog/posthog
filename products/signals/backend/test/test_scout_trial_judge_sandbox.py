from __future__ import annotations

import json
import asyncio
from inspect import unwrap
from types import SimpleNamespace
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase, override_settings

from asgiref.sync import async_to_sync, sync_to_async
from parameterized import parameterized
from rest_framework.test import APIClient
from temporalio.testing import ActivityEnvironment

from posthog.models import Integration, OAuthApplication
from posthog.models.scoping import team_scope
from posthog.temporal.oauth import SIGNALS_APP_CLIENT_ID_DEV

from products.mcp_store.backend.models import MCPServerInstallation
from products.signals.backend.scout_harness.trial_judge import TrialJudgeExecutionError, judge_trial_run
from products.signals.backend.test.test_scout_trial_judge import _snapshot, _verdict
from products.signals.backend.trial_judging_types import TrialJudgeVerdicts
from products.tasks.backend.logic.services.agent_command import CommandResult
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.oauth import create_oauth_access_token_for_run
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import (
    GetTaskProcessingContextInput,
    get_task_processing_context,
)
from products.tasks.backend.temporal.process_task.activities.provision_sandbox import (
    _build_environment_variables,
    _resolve_sandbox_github_token,
)
from products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox import (
    SendFollowupToSandboxInput,
    send_followup_to_sandbox,
)
from products.tasks.backend.temporal.process_task.activities.start_agent_server import _prepare_launch
from products.tasks.backend.temporal.process_task.workflow import ProcessTaskWorkflow

MODULE = "products.signals.backend.scout_harness.trial_judge"
SESSION_MODULE = "products.tasks.backend.logic.services.custom_prompt_multi_turn_runner"
FOLLOWUP_MODULE = "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox"
PROVISION_MODULE = "products.tasks.backend.temporal.process_task.activities.provision_sandbox"
START_MODULE = "products.tasks.backend.temporal.process_task.activities.start_agent_server"


class TestSandboxJudgeLifecycle(SimpleTestCase):
    @parameterized.expand(["success", "invalid_result", "cancelled", "startup_failure", "cleanup_failure"])
    async def test_judge_closes_its_sandbox_and_does_not_disclose_errors(self, outcome: str) -> None:
        snapshot = _snapshot()
        evidence = snapshot.runs[0]
        run = SimpleNamespace(
            id=uuid4(), task_id=uuid4(), state={"token_usage": {"input_tokens": 123, "output_tokens": 45}}
        )
        session = SimpleNamespace(task_run=run, end=AsyncMock())
        if outcome == "cleanup_failure":
            session.end.side_effect = RuntimeError("private fixture content must not appear in errors")
        output = TrialJudgeVerdicts.model_validate({"summary": "Synthetic assessment.", "criteria": [_verdict()]})
        if outcome == "invalid_result":
            output = output.model_copy(update={"criteria": output.criteria * 2})

        async def start(**kwargs):
            kwargs["before_task_dispatch"](run.id)
            if outcome == "cancelled":
                raise asyncio.CancelledError
            if outcome == "startup_failure":
                raise RuntimeError("private fixture content must not appear in errors")
            return session, output

        with (
            patch(f"{MODULE}._assert_scout_available"),
            patch(f"{MODULE}.read_trial_evidence_sources", return_value=evidence.sources),
            patch(f"{MODULE}.tasks_facade.get_task_by_origin_key", return_value=None),
            patch(f"{MODULE}.get_or_create_signals_sandbox_env", return_value=str(uuid4())),
            patch(f"{MODULE}.tasks_facade.attach_task_run_input_files"),
            patch(f"{MODULE}.tasks_facade.get_task_run", return_value=run),
            patch(f"{MODULE}.tasks_facade.update_task_run") as update_run,
            patch(f"{MODULE}.MultiTurnSession.start", side_effect=start),
        ):
            if outcome == "success":
                result = await judge_trial_run(snapshot, evidence)
                self.assertEqual(result.status, "judged")
                self.assertEqual((result.input_tokens, result.output_tokens), (123, 45))
                self.assertEqual(result.criteria[0].verdict, "pass")
                session.end.assert_awaited_once_with(status="completed", error=None)
                update_run.assert_not_called()
            elif outcome == "cancelled":
                with self.assertRaises(asyncio.CancelledError):
                    await judge_trial_run(snapshot, evidence)
                self.assertEqual(update_run.call_args.kwargs["validated_data"]["status"], "failed")
            else:
                with self.assertRaises(TrialJudgeExecutionError) as error:
                    await judge_trial_run(snapshot, evidence)
                self.assertNotIn("private fixture content", str(error.exception))
                self.assertEqual(update_run.call_args.kwargs["validated_data"]["status"], "failed")
                if outcome == "invalid_result":
                    self.assertEqual(session.end.call_args.kwargs["status"], "failed")

    @parameterized.expand(["missing_evidence", "existing_judge"])
    async def test_unavailable_input_and_existing_judge_do_not_start_a_paid_run(self, failure: str) -> None:
        snapshot = _snapshot()
        with (
            patch(f"{MODULE}._assert_scout_available"),
            patch(
                f"{MODULE}.read_trial_evidence_sources",
                side_effect=ValueError("private missing file") if failure == "missing_evidence" else None,
                return_value=snapshot.runs[0].sources,
            ),
            patch(f"{MODULE}.tasks_facade.get_task_by_origin_key", return_value=object()),
            patch(f"{MODULE}.MultiTurnSession.start", new_callable=AsyncMock) as start,
        ):
            with self.assertRaises(TrialJudgeExecutionError):
                await judge_trial_run(snapshot, snapshot.runs[0])
        start.assert_not_awaited()


class TestSandboxJudgeDispatch(BaseTest):
    @parameterized.expand([("valid_json", False), ("invalid_json", True)])
    @override_settings(
        DEBUG=False,
        SANDBOX_MCP_URL="https://mcp.example.com/mcp",
        SANDBOX_AI_GATEWAY_URL="https://gateway.example.com",
        SANDBOX_AI_GATEWAY_MINT_KEY="synthetic-mint-key",
        SANDBOX_AI_GATEWAY_PRODUCTS="signals_scout",
    )
    def test_ordinary_task_judges_attached_inputs_without_connectors_including_json_retry(
        self, _name: str, retry_json: bool
    ) -> None:
        OAuthApplication.objects.get_or_create(
            client_id=SIGNALS_APP_CLIENT_ID_DEV,
            defaults={
                "name": "Synthetic Signals sandbox",
                "client_type": OAuthApplication.CLIENT_PUBLIC,
                "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
                "redirect_uris": "https://example.com/callback",
                "algorithm": "RS256",
            },
        )
        Integration.objects.create(team=self.team, kind="github", integration_id="12345", config={})
        MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            scope="shared",
            display_name="Synthetic connector",
            url="https://connector.example.com/mcp",
        )
        snapshot = _snapshot().model_copy(update={"team_id": self.team.id, "user_id": self.user.id})
        evidence = snapshot.runs[0]
        output = TrialJudgeVerdicts.model_validate({"summary": "Synthetic assessment.", "criteria": [_verdict()]})
        dispatched: list[TaskRun] = []
        log_lines: list[str] = []

        def append_response(text: str) -> None:
            log_lines.extend(
                [
                    json.dumps(
                        {
                            "notification": {
                                "method": "session/update",
                                "params": {
                                    "update": {
                                        "sessionUpdate": "agent_message",
                                        "content": {"type": "text", "text": text},
                                    }
                                },
                            }
                        }
                    ),
                    json.dumps({"notification": {"result": {"stopReason": "end_turn"}}}),
                ]
            )

        append_response("The synthetic check passed." if retry_json else output.model_dump_json())

        def send_message(*_args: object, **_kwargs: object) -> CommandResult:
            append_response(output.model_dump_json())
            return CommandResult(success=True, status_code=200)

        async def signal(signal: object, message: str | None = None, **_kwargs: object) -> None:
            if signal is ProcessTaskWorkflow.send_followup_message:
                await sync_to_async(ActivityEnvironment().run)(
                    send_followup_to_sandbox,
                    SendFollowupToSandboxInput(run_id=str(dispatched[0].id), message=message, posthog_mcp_scopes=[]),
                )

        workflow_handle = MagicMock(signal=AsyncMock(side_effect=signal))
        client = MagicMock()
        client.get_workflow_handle.return_value = workflow_handle

        def dispatch(run: TaskRun, **_kwargs: object) -> None:
            run.refresh_from_db()
            self.assertEqual(run.task.origin_product, Task.OriginProduct.SIGNALS_SCOUT_SUGGESTIONS)
            self.assertFalse(run.task.is_scout_experiment)
            self.assertNotIn("scout_trial_judge", run.state)
            self.assertEqual(run.state["pending_dispatch"]["posthog_mcp_scopes"], [])
            self.assertEqual(run.state["pending_user_message_id"], str(run.id))
            self.assertEqual(run.state["pending_user_artifact_ids"], [item["id"] for item in run.artifacts])
            self.assertEqual([item["name"] for item in run.artifacts], [file.filename for file in evidence.files])
            self.assertNotIn(evidence.sources[0].text, run.state["pending_user_message"])
            self.assertEqual(run.state["model"], snapshot.judge_model)
            self.assertEqual(run.state["reasoning_effort"], "high")
            self.assertEqual(run.state["mcp_gateway_server_ids"], [])
            self.assertEqual(run.task.mcp_builtin_agent_key, "scout")
            self.assertEqual(run.task.mcp_gateway_server_allowlist, [])
            self.assertIsNone(run.task.repository)
            self.assertTrue(run.task.internal)
            for artifact in run.artifacts:
                self.assertIn(f"/{snapshot.team_id}/evaluations/{snapshot.evaluation_id}/", artifact["storage_path"])
                self.assertIn(str(evidence.launch_id), artifact["storage_path"])

            context = ActivityEnvironment().run(
                unwrap(get_task_processing_context), GetTaskProcessingContextInput(run_id=str(run.id))
            )
            github_token = _resolve_sandbox_github_token(
                context, task=run.task, actor_user=self.user, repository=None, has_repo=False
            )
            self.assertEqual(github_token, "")
            access_token = create_oauth_access_token_for_run(run.task, context.state, scopes=[], run_id=run.id)
            environment = _build_environment_variables(context, run.task, github_token, access_token)
            self.assertEqual(environment["AI_GATEWAY_TOKEN"], "phe_synthetic_gateway")
            self.assertEqual(environment["POSTHOG_PERSONAL_API_KEY"], access_token)
            self.assertNotIn("GITHUB_TOKEN", environment)
            self.assertNotIn("GH_TOKEN", environment)
            launch = _prepare_launch(context, [], "synthetic-sandbox")
            self.assertEqual(launch.mcp_configs, [])
            self.assertEqual(launch.relayed_mcp_servers, [])

            api = APIClient()
            api.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
            url = f"/api/projects/{self.team.id}/tasks/{run.task_id}/runs/{run.id}/artifacts/download/"
            response = api.post(url, {"storage_path": run.artifacts[0]["storage_path"]}, format="json")
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(
                api.post(url, {"storage_path": "unrelated-run/private-log.jsonl"}, format="json").status_code,
                404,
            )
            dispatched.append(run)

        with (
            team_scope(self.team.id, canonical=True),
            patch(f"{MODULE}._assert_scout_available"),
            patch(f"{MODULE}.read_trial_evidence_sources", return_value=evidence.sources),
            patch("posthoganalytics.feature_enabled", return_value=False),
            patch("posthog.temporal.oauth.get_instance_region", return_value=None),
            patch(
                "products.tasks.backend.logic.services.workflow_dispatch.enqueue_or_start_workflow",
                side_effect=dispatch,
            ),
            patch(f"{SESSION_MODULE}.async_connect", new=AsyncMock(return_value=client)),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch("posthog.storage.object_storage.read", side_effect=lambda *_args, **_kwargs: "\n".join(log_lines)),
            patch("posthog.storage.object_storage.read_bytes", return_value=b"Synthetic attached evidence"),
            patch(
                "products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post",
                return_value=MagicMock(status_code=200, json=lambda: {"token": "phe_synthetic_gateway"}),
            ),
            patch(f"{PROVISION_MODULE}.get_sandbox_jwt_public_key", return_value="synthetic-public-key"),
            patch(f"{START_MODULE}.create_codex_subscription_run_token", return_value="synthetic-codex-token"),
            patch(f"{FOLLOWUP_MODULE}.create_sandbox_connection_token", return_value="synthetic-connection-token"),
            patch(f"{FOLLOWUP_MODULE}.get_sandbox_mcp_session_user", return_value=None),
            patch(f"{FOLLOWUP_MODULE}.mark_sandbox_mcp_session"),
            patch(f"{FOLLOWUP_MODULE}.publish_task_run_stream_event"),
            patch(
                f"{FOLLOWUP_MODULE}.send_refresh_session", return_value=CommandResult(success=True, status_code=200)
            ) as refresh,
            patch(f"{FOLLOWUP_MODULE}.send_user_message", side_effect=send_message) as followup,
            patch(f"{FOLLOWUP_MODULE}.get_sandbox_github_token") as refresh_github,
        ):
            result = async_to_sync(judge_trial_run)(snapshot, evidence)
            self.assertEqual(result.status, "judged")
            self.assertEqual(len(dispatched), 1)
            with self.assertRaisesMessage(TrialJudgeExecutionError, "already has a judge task"):
                async_to_sync(judge_trial_run)(snapshot, evidence)
            self.assertEqual(
                Task.objects.filter(team_id=self.team.id, origin_key__startswith="scout-trial-judge:").count(), 1
            )
            self.assertEqual(TaskRun.objects.filter(team_id=self.team.id, task=dispatched[0].task).count(), 1)
            self.assertEqual(workflow_handle.signal.call_args.kwargs["args"], ["completed", None])
            self.assertEqual(result.criteria[0].verdict, "pass")
            self.assertEqual(followup.call_count, int(retry_json))
            if retry_json:
                self.assertEqual(followup.call_args.args[0].id, dispatched[0].id)
                self.assertIn("Return the complete JSON object", followup.call_args.args[1])
            refresh.assert_not_called()
            refresh_github.assert_not_called()
