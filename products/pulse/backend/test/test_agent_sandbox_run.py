import json
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.pulse.backend.agent.mission import build_general_brief_mission
from products.pulse.backend.agent.prompt import render_mission_prompt
from products.pulse.backend.agent.sandbox_run import MissionRunError, ReportTooLargeError, run_mission
from products.pulse.backend.models import ProductBrief
from products.tasks.backend.facade.sandbox import McpServerConfig

REPORT: dict[str, Any] = {"sections": [], "opportunities": [], "window_start": "x", "window_end": "y", "artifacts": []}
RUN_ID = "wf-run-1"


class TestRunMission(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.get_cls = self._patch("get_sandbox_class")
        self.mint = self._patch("create_oauth_access_token_for_user", return_value="tok")
        self.connection_token = self._patch("create_sandbox_connection_token", return_value="jwt")
        self.build_env = self._patch("build_sandbox_environment_variables", return_value={"POSTHOG_PROJECT_ID": "1"})
        self.send = self._patch("send_agent_command")
        self.storage = self._patch("object_storage")
        self.send.return_value = MagicMock(success=True, turn_in_flight=False, error=None)

    def _patch(self, name: str, **kwargs: Any) -> MagicMock:
        patcher = patch(f"products.pulse.backend.agent.sandbox_run.{name}", **kwargs)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def _bundle(self):
        with team_scope(self.team.pk, canonical=True):
            brief = ProductBrief.objects.create(team=self.team, trigger=ProductBrief.Trigger.ON_DEMAND)
        return build_general_brief_mission(team=self.team, brief=brief, config=None, items=[])

    def _sandbox(self, report_stdout: str) -> MagicMock:
        sandbox = MagicMock()
        sandbox.id = "sb-123"
        sandbox.get_connect_credentials.return_value = MagicMock(url="https://sb.example.com", token="ct")

        def execute(command: str, timeout_seconds: int | None = None) -> MagicMock:
            if "report.json" in command:
                if command.startswith("test -s"):
                    return MagicMock(stdout="done" if report_stdout else "", exit_code=0)
                return MagicMock(stdout=report_stdout, exit_code=0)
            return MagicMock(stdout="log line", exit_code=0)

        sandbox.execute.side_effect = execute
        self.get_cls.return_value.create.return_value = sandbox
        return sandbox

    def test_happy_path_returns_untouched_report_and_tears_down(self) -> None:
        sandbox = self._sandbox(json.dumps(REPORT))

        result = run_mission(self._bundle(), user=self.user, run_id=RUN_ID)

        assert result.report == REPORT
        assert result.agent_session_ref == "sb-123"
        assert result.transcript_key is not None
        self.storage.write.assert_called_once()
        assert self.storage.write.call_args.args[0] == result.transcript_key
        sandbox.destroy.assert_called_once()

    def test_launch_contract_leash_egress_and_mission_delivery(self) -> None:
        bundle = self._bundle()
        self._sandbox(json.dumps(REPORT))

        run_mission(bundle, user=self.user, run_id=RUN_ID)

        self.mint.assert_called_once_with(
            self.user, self.team.pk, scopes=["query:read", "insight:read", "dashboard:read"]
        )
        create_config = self.get_cls.return_value.create.call_args.args[0]
        assert create_config.environment_variables == {"POSTHOG_PROJECT_ID": "1"}
        assert create_config.outbound_domain_allowlist
        sandbox = self.get_cls.return_value.create.return_value
        _, launch_kwargs = sandbox.start_agent_server.call_args
        assert launch_kwargs["repository"] is None
        assert launch_kwargs["create_pr"] is False
        assert launch_kwargs["task_id"] == bundle.brief_id
        assert launch_kwargs["run_id"] == RUN_ID
        assert launch_kwargs["allowed_domains"] == create_config.outbound_domain_allowlist
        mcp_configs = launch_kwargs["mcp_configs"]
        # Real instances required: both sandbox implementations call .to_dict() on each entry.
        assert all(isinstance(config, McpServerConfig) for config in mcp_configs)
        assert mcp_configs[0].name == "posthog"
        assert {"name": "Authorization", "value": "Bearer tok"} in mcp_configs[0].headers
        _, send_kwargs = self.send.call_args
        assert send_kwargs["method"] == "user_message"
        assert send_kwargs["auth_token"] == "jwt"
        assert send_kwargs["params"]["content"] == render_mission_prompt(bundle)
        assert send_kwargs["params"]["messageId"] == f"mission-{bundle.brief_id}"

    def test_destroys_sandbox_when_agent_errors(self) -> None:
        sandbox = self._sandbox("")
        self.send.return_value = MagicMock(success=False, turn_in_flight=False, error="boom")

        with self.assertRaises(MissionRunError):
            run_mission(self._bundle(), user=self.user, run_id=RUN_ID)
        sandbox.destroy.assert_called_once()

    @parameterized.expand(
        [
            ("missing", "", MissionRunError),
            ("invalid_json", "not json", MissionRunError),
            ("oversized", json.dumps({**REPORT, "sections": [{"markdown": "x" * 600_000}]}), ReportTooLargeError),
        ]
    )
    def test_bad_report_raises_and_tears_down(self, _name: str, stdout: str, expected: type[Exception]) -> None:
        sandbox = self._sandbox(stdout)

        with self.assertRaises(expected):
            run_mission(self._bundle(), user=self.user, run_id=RUN_ID)
        sandbox.destroy.assert_called_once()

    def test_turn_in_flight_polls_for_report_instead_of_failing(self) -> None:
        self._sandbox(json.dumps(REPORT))
        self.send.return_value = MagicMock(success=False, turn_in_flight=True, error="Sandbox request timed out")

        result = run_mission(self._bundle(), user=self.user, run_id=RUN_ID)
        assert result.report == REPORT

    def test_transcript_upload_failure_does_not_fail_the_run(self) -> None:
        self._sandbox(json.dumps(REPORT))
        self.storage.write.side_effect = RuntimeError("s3 down")

        result = run_mission(self._bundle(), user=self.user, run_id=RUN_ID)
        assert result.report == REPORT
        assert result.transcript_key is None
