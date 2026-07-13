import json
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

import jwt
from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.pulse.backend.agent.mission import build_general_brief_mission
from products.pulse.backend.agent.prompt import render_mission_prompt
from products.pulse.backend.agent.sandbox_run import (
    MissionRunError,
    ReportTooLargeError,
    _SandboxRunRef,
    cleanup_sandbox,
    finalize_mission,
    launch_mission,
)
from products.pulse.backend.models import ProductBrief
from products.tasks.backend.facade.sandbox import McpServerConfig, SandboxNotFoundError, create_sandbox_connection_token
from products.tasks.backend.logic.services.connection_token import reset_sandbox_jwt_key_cache
from products.tasks.backend.tests.test_api import TEST_RSA_PRIVATE_KEY

REPORT: dict[str, Any] = {"sections": [], "opportunities": [], "window_start": "x", "window_end": "y", "artifacts": []}
RUN_ID = "wf-run-1"


class _SandboxRunTestBase(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.get_cls = self._patch("get_sandbox_class")
        self.mint = self._patch("create_oauth_access_token_for_user", return_value="tok")
        self.connection_token = self._patch("create_sandbox_connection_token", return_value="jwt")
        self.ingest_token = self._patch("create_sandbox_event_ingest_token", return_value="ingest-tok")
        self.build_env = self._patch(
            "build_sandbox_environment_variables",
            return_value={"POSTHOG_PROJECT_ID": "1", "POSTHOG_API_URL": "http://localhost:8010"},
        )
        self.send = self._patch("send_agent_command")
        self.storage = self._patch("object_storage")
        self.send.return_value = MagicMock(success=True, turn_in_flight=False, error=None, status_code=200)

    def _patch(self, name: str, **kwargs: Any) -> MagicMock:
        patcher = patch(f"products.pulse.backend.agent.sandbox_run.{name}", **kwargs)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def _bundle(self):
        with team_scope(self.team.pk, canonical=True):
            brief = ProductBrief.objects.create(team=self.team, trigger=ProductBrief.Trigger.ON_DEMAND)
        return build_general_brief_mission(team=self.team, brief=brief, config=None, items=[])

    def _sandbox(self, report_stdout: str = "", log_stdout: str = "log line") -> MagicMock:
        sandbox = MagicMock()
        sandbox.id = "sb-123"
        sandbox.get_connect_credentials.return_value = MagicMock(url="https://sb.example.com", token="ct")

        def execute(command: str, timeout_seconds: int | None = None) -> MagicMock:
            if "report.json" in command:
                return MagicMock(stdout=report_stdout, exit_code=0)
            return MagicMock(stdout=log_stdout, exit_code=0)

        sandbox.execute.side_effect = execute
        return sandbox

    def _for_launch(self, sandbox: MagicMock) -> None:
        self.get_cls.return_value.create.return_value = sandbox

    def _for_finalize(self, sandbox: MagicMock) -> None:
        self.get_cls.return_value.get_by_id.return_value = sandbox


class TestLaunchMission(_SandboxRunTestBase):
    def test_streams_to_pulse_callback_and_leaves_sandbox_running(self) -> None:
        sandbox = self._sandbox()
        self._for_launch(sandbox)
        on_created = MagicMock()

        sandbox_id = launch_mission(self._bundle(), user=self.user, run_id=RUN_ID, on_sandbox_created=on_created)

        assert sandbox_id == "sb-123"
        # The sandbox must survive the turn — finalize (after the callback) tears it down, not launch.
        sandbox.destroy.assert_not_called()
        _, launch_kwargs = sandbox.start_agent_server.call_args
        assert launch_kwargs["event_ingest_url"] == f"http://localhost:8010/internal/pulse/runs/{RUN_ID}/agent-events/"
        assert launch_kwargs["event_ingest_token"] == "ingest-tok"

    def test_stashes_completion_context_before_delivering_the_mission(self) -> None:
        # Delivery starts the turn, so the token must be stashed first or a fast turn's
        # turn-complete callback could arrive before the token is resolvable.
        sandbox = self._sandbox()
        self._for_launch(sandbox)
        order = MagicMock()
        order.attach_mock(self.send, "send")
        on_created = MagicMock(side_effect=lambda _sid: order.created())

        launch_mission(self._bundle(), user=self.user, run_id=RUN_ID, on_sandbox_created=on_created)

        on_created.assert_called_once_with("sb-123")
        assert [c[0] for c in order.mock_calls] == ["created", "send"]

    def test_launch_contract_leash_egress_and_mission_delivery(self) -> None:
        bundle = self._bundle()
        self._for_launch(self._sandbox())

        launch_mission(bundle, user=self.user, run_id=RUN_ID, on_sandbox_created=MagicMock())

        self.mint.assert_called_once_with(
            self.user, self.team.pk, scopes=["query:read", "insight:read", "dashboard:read"]
        )
        create_config = self.get_cls.return_value.create.call_args.args[0]
        assert create_config.outbound_domain_allowlist
        _, launch_kwargs = self.get_cls.return_value.create.return_value.start_agent_server.call_args
        assert launch_kwargs["repository"] is None
        assert launch_kwargs["create_pr"] is False
        mcp_configs = launch_kwargs["mcp_configs"]
        # Real instances required: both sandbox implementations call .to_dict() on each entry.
        assert all(isinstance(config, McpServerConfig) for config in mcp_configs)
        assert {"name": "Authorization", "value": "Bearer tok"} in mcp_configs[0].headers
        _, send_kwargs = self.send.call_args
        assert send_kwargs["method"] == "user_message"
        assert send_kwargs["auth_token"] == "jwt"
        assert send_kwargs["params"]["content"] == render_mission_prompt(bundle)
        assert send_kwargs["params"]["messageId"] == f"mission-{bundle.brief_id}"

    def test_destroys_sandbox_when_delivery_fails(self) -> None:
        sandbox = self._sandbox()
        self._for_launch(sandbox)
        self.send.return_value = MagicMock(success=False, turn_in_flight=False, error="boom", status_code=500)

        with self.assertRaises(MissionRunError):
            launch_mission(self._bundle(), user=self.user, run_id=RUN_ID, on_sandbox_created=MagicMock())
        sandbox.destroy.assert_called_once()

    def test_turn_in_flight_is_a_successful_delivery(self) -> None:
        sandbox = self._sandbox()
        self._for_launch(sandbox)
        self.send.return_value = MagicMock(success=False, turn_in_flight=True, error="timed out", status_code=0)

        sandbox_id = launch_mission(self._bundle(), user=self.user, run_id=RUN_ID, on_sandbox_created=MagicMock())
        assert sandbox_id == "sb-123"
        sandbox.destroy.assert_not_called()


class TestFinalizeMission(_SandboxRunTestBase):
    def test_reads_report_persists_transcript_and_tears_down(self) -> None:
        sandbox = self._sandbox(report_stdout=json.dumps(REPORT))
        self._for_finalize(sandbox)

        result = finalize_mission("sb-123", self._bundle(), run_id=RUN_ID)

        assert result.report == REPORT
        assert result.agent_session_ref == "sb-123"
        assert result.transcript_key is not None
        self.storage.write.assert_called_once()
        sandbox.destroy.assert_called_once()

    @parameterized.expand(
        [
            ("missing", "", MissionRunError),
            ("invalid_json", "not json", MissionRunError),
            ("not_object", json.dumps([1, 2, 3]), MissionRunError),
            ("oversized", json.dumps({**REPORT, "sections": [{"markdown": "x" * 600_000}]}), ReportTooLargeError),
        ]
    )
    def test_bad_report_raises_and_tears_down(self, _name: str, stdout: str, expected: type[Exception]) -> None:
        sandbox = self._sandbox(report_stdout=stdout)
        self._for_finalize(sandbox)

        with self.assertRaises(expected):
            finalize_mission("sb-123", self._bundle(), run_id=RUN_ID)
        sandbox.destroy.assert_called_once()

    def test_empty_transcript_persists_nothing(self) -> None:
        sandbox = self._sandbox(report_stdout=json.dumps(REPORT), log_stdout="")
        self._for_finalize(sandbox)

        result = finalize_mission("sb-123", self._bundle(), run_id=RUN_ID)
        assert result.transcript_key is None
        self.storage.write.assert_not_called()

    def test_transcript_upload_failure_does_not_fail_the_run(self) -> None:
        sandbox = self._sandbox(report_stdout=json.dumps(REPORT))
        self._for_finalize(sandbox)
        self.storage.write.side_effect = RuntimeError("s3 down")

        result = finalize_mission("sb-123", self._bundle(), run_id=RUN_ID)
        assert result.report == REPORT
        assert result.transcript_key is None


class TestCleanupSandbox(SimpleTestCase):
    # cleanup_sandbox only takes a sandbox id — no DB needed, so this stays a SimpleTestCase.
    def test_destroys_sandbox(self) -> None:
        with patch("products.pulse.backend.agent.sandbox_run.get_sandbox_class") as get_cls:
            sandbox = get_cls.return_value.get_by_id.return_value
            cleanup_sandbox("sb-123")
            sandbox.destroy.assert_called_once()

    def test_missing_sandbox_is_a_noop(self) -> None:
        with patch("products.pulse.backend.agent.sandbox_run.get_sandbox_class") as get_cls:
            get_cls.return_value.get_by_id.side_effect = SandboxNotFoundError("gone", {}, RuntimeError("gone"))
            # A sandbox that already self-expired must not raise out of cleanup.
            cleanup_sandbox("sb-123")


@override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY, SANDBOX_JWT_PUBLIC_KEY=None)
class TestSandboxConnectionTokenContract(SimpleTestCase):
    """Runs the real facade token minter against a run-shaped stand-in (no TaskRun row). Everything
    else mocks this call, so this is the only guard that a future attribute the minter reads off the
    run — one the ``_SandboxRunRef`` cast hides from mypy — surfaces as a failure, not a 3am runtime
    AttributeError on live pulse runs."""

    def setUp(self) -> None:
        super().setUp()
        reset_sandbox_jwt_key_cache()
        self.addCleanup(reset_sandbox_jwt_key_cache)

    def test_ref_carries_the_claims_the_minter_reads(self) -> None:
        ref = _SandboxRunRef(id="run-1", task_id="brief-1", team_id=7, mode="background", state={})

        token = create_sandbox_connection_token(ref, user_id=42, distinct_id="d-42")

        claims = jwt.decode(token, options={"verify_signature": False})
        assert claims["run_id"] == "run-1"
        assert claims["task_id"] == "brief-1"
        assert claims["team_id"] == 7
        assert claims["mode"] == "background"
        assert claims["user_id"] == 42
