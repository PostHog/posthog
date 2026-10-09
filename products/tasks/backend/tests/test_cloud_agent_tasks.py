from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Integration, Team
from posthog.models.user import User

from products.tasks.backend.constants import COMPUTE_WAIVED_REASON_STATE_KEY
from products.tasks.backend.exceptions import COMPUTE_USAGE_LIMIT_ERROR_MESSAGE, ComputeBillingLimitError
from products.tasks.backend.facade import (
    api as facade,
    cloud_agents,
    contracts,
)
from products.tasks.backend.facade.billing import get_task_run_billing
from products.tasks.backend.facade.compute import DEFAULT_SANDBOX_SIZE, SandboxSize
from products.tasks.backend.logic.services.sandbox import SandboxConfig
from products.tasks.backend.logic.services.sandbox_usage import open_sandbox_session
from products.tasks.backend.models import SandboxSession, Task, TaskClientProvenance, TaskRun
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import (
    TaskProcessingContext,
    _is_burstable_sandbox_resources_enabled,
)
from products.tasks.backend.visibility import task_visibility_q

PR_A = "https://github.com/acme/app/pull/7"
PR_B = "https://github.com/acme/app/pull/8"


def _run_dto(status: str, *, error_message: str | None = None, state: dict | None = None) -> contracts.TaskRunDTO:
    return contracts.TaskRunDTO(
        id=uuid4(),
        task_id=uuid4(),
        team_id=1,
        status=status,
        environment="cloud",
        stage=None,
        branch=None,
        error_message=error_message,
        output=None,
        state=state or {},
        is_terminal=status in ("completed", "failed", "cancelled"),
    )


class TestClassifyTaskRunEnd(SimpleTestCase):
    @parameterized.expand(
        [
            ("completed", "completed", None, {}, "done"),
            ("completed_after_idle_timeout", "completed", None, {"timed_out_inactivity": True}, "done"),
            ("cancelled", "cancelled", "Stopped by user", {"cancel_requested_at": "now"}, "cancelled"),
            ("cancelled_wins_over_a_timeout_marker", "cancelled", None, {"timed_out_inactivity": True}, "cancelled"),
            ("failed", "failed", "Sandbox stopped; resume to continue", {"sandbox_gone": True}, "error"),
            ("failed_without_a_message", "failed", None, {}, "error"),
            (
                "agent_lost",
                "failed",
                "The agent stopped before finishing its turn",
                {"timed_out_inactivity": True},
                "timeout",
            ),
            ("wall_clock_cap", "failed", None, {"timed_out_wall_clock": True}, "timeout"),
            (
                "usage_limit",
                "failed",
                ComputeBillingLimitError({"team_id": 1}).message,
                {},
                "usage_limit",
            ),
            (
                "organization_deactivated",
                "failed",
                ComputeBillingLimitError({"team_id": 1}, "organization_deactivated").message,
                {},
                "error",
            ),
        ]
    )
    def test_run_end_is_classified(
        self, _name: str, status: str, error_message: str | None, state: dict, expected: str
    ) -> None:
        assert (
            cloud_agents.classify_task_run_end(_run_dto(status, error_message=error_message, state=state)) == expected
        )

    @parameterized.expand([("queued",), ("in_progress",), ("not_started",)])
    def test_active_run_has_no_end(self, status: str) -> None:
        with self.assertRaises(ValueError):
            cloud_agents.classify_task_run_end(_run_dto(status))

    def test_usage_limit_message_is_the_one_the_billing_error_carries(self) -> None:
        assert ComputeBillingLimitError({"team_id": 1}).message == COMPUTE_USAGE_LIMIT_ERROR_MESSAGE


@patch("products.tasks.backend.models.TaskRun.publish_stream_state_event", MagicMock())
@patch("products.tasks.backend.temporal.client.execute_task_processing_workflow", MagicMock())
class TestCloudAgentTasks(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        Integration.objects.create(team=self.team, kind="github", config={})

    def _create(self, **overrides: Any) -> contracts.CloudAgentTaskDTO:
        kwargs: dict[str, Any] = {
            "team_id": self.team.id,
            "user_id": self.user.id,
            "prompt": "Fix the flaky test",
            "title": "Flaky test",
            "repository": "posthog/posthog",
            "branch": None,
            "create_pr": True,
            "origin_key": None,
            "billable": True,
            "sandbox_size": SandboxSize.CPU_8_MEMORY_32,
            "model": None,
            "runtime_adapter": None,
            "reasoning_effort": None,
            "inactivity_timeout_seconds": None,
            "extra_run_state": None,
        }
        kwargs.update(overrides)
        return cloud_agents.create_cloud_agent_task(**kwargs)

    def _resume(self, created: contracts.CloudAgentTaskDTO, **overrides: Any) -> contracts.TaskRunDTO:
        assert created.run is not None
        kwargs: dict[str, Any] = {
            "team_id": self.team.id,
            "task_id": created.task_id,
            "user_id": self.user.id,
            "previous_run_id": created.run.id,
            "message": "Also update the docs",
            "sandbox_size": SandboxSize.CPU_8_MEMORY_32,
            "model": None,
            "reasoning_effort": None,
            "inactivity_timeout_seconds": None,
            "extra_run_state": None,
        }
        kwargs.update(overrides)
        return cloud_agents.resume_cloud_agent_task(**kwargs)

    def _finish(self, run_id: Any, status: str = TaskRun.Status.COMPLETED) -> None:
        TaskRun.objects.filter(id=run_id).update(status=status)

    def _context(self, run: TaskRun) -> TaskProcessingContext:
        return TaskProcessingContext(
            task_id=str(run.task_id),
            run_id=str(run.id),
            team_id=run.team_id,
            team_uuid=str(self.team.uuid),
            organization_id=str(self.team.organization_id),
            github_integration_id=None,
            repository="posthog/posthog",
            distinct_id="user-1",
            state=run.state,
        )

    def test_create_stamps_a_reserved_internal_background_task(self) -> None:
        schema = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
        created = self._create(create_pr=False, output_schema=schema)

        task = Task.objects.get(id=created.task_id)
        assert created.created is True
        assert task.json_schema == schema
        assert created.run is not None
        assert (task.origin_product, task.internal, task.channel_id) == (Task.OriginProduct.CLOUD_AGENTS, True, None)
        assert (created.run.mode, created.run.status) == ("background", TaskRun.Status.QUEUED)
        state = created.run.state
        assert state["initial_prompt_override"] == "Fix the flaky test"
        assert state["end_run_when_done"] is True
        assert state["pending_dispatch"]["posthog_mcp_scopes"] == "read_only"
        assert state["pending_dispatch"]["create_pr"] is False
        assert state["runtime_adapter"] == "claude"
        assert state["model"]

    def test_created_task_is_not_in_the_default_task_list(self) -> None:
        created = self._create()

        listed = Task.objects.filter(team_id=self.team.id, internal=False).filter(task_visibility_q(self.user.id))

        assert created.task_id not in set(listed.values_list("id", flat=True))

    @parameterized.expand(
        [
            ("default_size", DEFAULT_SANDBOX_SIZE, 4.0, 16.0),
            ("small_size", SandboxSize.CPU_1_MEMORY_2, 1.0, 2.0),
            ("large_size", SandboxSize.CPU_16_MEMORY_64, 16.0, 64.0),
        ]
    )
    def test_create_pins_a_fixed_sandbox_of_the_selected_size(
        self, _name: str, size: SandboxSize, cpu_cores: float, memory_gb: float
    ) -> None:
        created = self._create(sandbox_size=size)

        assert created.run is not None
        run = TaskRun.objects.get(id=created.run.id)
        assert run.state["sandbox_size"] == size.value
        assert self._context(run).sandbox_resource_overrides() == {"cpu_cores": cpu_cores, "memory_gb": memory_gb}
        assert _is_burstable_sandbox_resources_enabled(run_id=str(run.id), state=run.state) is False

    @parameterized.expand(
        [
            ("billable", True, TaskClientProvenance.CLOUD_AGENTS),
            ("not_billable", False, None),
        ]
    )
    def test_billable_is_carried_onto_the_sandbox_sessions_of_the_run(
        self, _name: str, billable: bool, expected: TaskClientProvenance | None
    ) -> None:
        created = self._create(billable=billable)
        assert created.run is not None

        open_sandbox_session(run_id=created.run.id, sandbox_id="sb-1", config=SandboxConfig(name="sb"), required=True)

        assert Task.objects.get(id=created.task_id).client_provenance == expected
        session = SandboxSession.objects.for_team(self.team.id).get(sandbox_id="sb-1")
        assert (session.client_provenance, session.origin_product) == (expected, Task.OriginProduct.CLOUD_AGENTS)

    def test_caller_run_state_cannot_replace_the_server_keys(self) -> None:
        created = self._create(
            extra_run_state={
                "cloud_agent_session_id": "session-1",
                "sandbox_size": "1x2",
                "burstable_sandbox_resources_enabled": True,
                "end_run_when_done": False,
            }
        )

        assert created.run is not None
        state = created.run.state
        assert state["cloud_agent_session_id"] == "session-1"
        assert state["sandbox_size"] == "8x32"
        assert state["burstable_sandbox_resources_enabled"] is False
        assert state["end_run_when_done"] is True

    def test_repeated_origin_key_returns_the_first_task(self) -> None:
        first = self._create(origin_key="key-1")
        replay = self._create(origin_key="key-1", prompt="A different prompt", sandbox_size=SandboxSize.CPU_1_MEMORY_2)

        assert replay.created is False
        assert first.run is not None and replay.run is not None
        assert (replay.task_id, replay.run.id) == (first.task_id, first.run.id)
        assert Task.objects.filter(team_id=self.team.id, origin_key="key-1").count() == 1
        assert TaskRun.objects.filter(task_id=first.task_id).count() == 1

    def test_origin_key_of_another_origin_is_a_conflict(self) -> None:
        Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=Task.OriginProduct.WORKFLOW,
            origin_key="key-1",
            created_by=self.user,
        )

        with self.assertRaises(cloud_agents.CloudAgentTaskOriginKeyConflict):
            self._create(origin_key="key-1")

    @parameterized.expand(
        [
            ("model_of_another_runtime", {"model": "gpt-5.5", "runtime_adapter": "claude"}),
            ("unknown_runtime", {"runtime_adapter": "not-a-runtime"}),
            ("reasoning_effort_that_the_model_does_not_have", {"reasoning_effort": "not-an-effort"}),
            ("output_schema_of_a_string", {"output_schema": {"type": "string"}}),
            (
                "output_schema_with_a_name_that_tasks_writes",
                {"output_schema": {"type": "object", "properties": {"pr_merged": {"type": "boolean"}}}},
            ),
        ]
    )
    def test_invalid_request_creates_nothing(self, _name: str, overrides: dict[str, Any]) -> None:
        with self.assertRaises(cloud_agents.CloudAgentTaskInvalid):
            self._create(**overrides)

        assert not Task.objects.filter(team_id=self.team.id, origin_product=Task.OriginProduct.CLOUD_AGENTS).exists()

    def test_resume_creates_a_successor_that_keeps_size_scopes_and_provenance(self) -> None:
        created = self._create(create_pr=False, sandbox_size=SandboxSize.CPU_2_MEMORY_4)
        assert created.run is not None
        self._finish(created.run.id)
        other_member = User.objects.create_and_join(self.organization, "other@example.com", "password")

        with patch("products.tasks.backend.facade.api._trigger_task_processing_workflow", return_value=None) as trigger:
            successor = self._resume(
                created,
                user_id=other_member.id,
                sandbox_size=SandboxSize.CPU_8_MEMORY_32,
                inactivity_timeout_seconds=300,
                extra_run_state={"cloud_agent_session_id": "session-1", "burstable_sandbox_resources_enabled": True},
            )

        assert successor.id != created.run.id
        assert successor.task_id == created.task_id
        state = successor.state
        assert state["resume_from_run_id"] == str(created.run.id)
        assert state["pending_user_message"] == "Also update the docs"
        assert state["sandbox_size"] == "8x32"
        assert (state["sandbox_cpu_cores"], state["sandbox_memory_gb"]) == (8.0, 32.0)
        assert state["burstable_sandbox_resources_enabled"] is False
        assert state["end_run_when_done"] is True
        assert state["inactivity_timeout_seconds"] == 300
        assert state["cloud_agent_session_id"] == "session-1"
        assert (state["runtime_adapter"], state["model"]) == (
            created.run.state["runtime_adapter"],
            created.run.state["model"],
        )
        assert trigger.call_args.kwargs["create_pr"] is False
        assert trigger.call_args.kwargs["posthog_mcp_scopes"] == "read_only"
        assert Task.objects.get(id=created.task_id).client_provenance == TaskClientProvenance.CLOUD_AGENTS
        assert cloud_agents.list_cloud_agent_task_run_ids(team_id=self.team.id, task_id=created.task_id) == [
            created.run.id,
            successor.id,
        ]

    @parameterized.expand(
        [
            ("posthog_credits", None, "posthog-gateway", "relay", False),
            ("posthog_decision", {}, "posthog-gateway", "relay", False),
            (
                "stored_subscription",
                {"claude_model_access": "own-subscription", "claude_subscription_source": "server"},
                "own-subscription",
                "server",
                True,
            ),
        ]
    )
    def test_create_stamps_the_inference_mode_and_makes_the_caller_its_owner(
        self, _name: str, inference_state: dict[str, Any] | None, access: str, source: str, has_owner: bool
    ) -> None:
        created = self._create(inference_state=inference_state)

        assert created.run is not None
        state = TaskRun.objects.get(id=created.run.id).state
        assert state["claude_model_access"] == access
        assert state["codex_model_access"] == "posthog-gateway"
        assert state["claude_subscription_source"] == source
        assert state.get("claude_subscription_user_id") == (self.user.id if has_owner else None)

    @parameterized.expand(
        [
            ("model_access_in_extra_state", {"extra_run_state": {"claude_model_access": "own-subscription"}}),
            ("source_in_extra_state", {"extra_run_state": {"claude_subscription_source": "server"}}),
            ("owner_in_extra_state", {"extra_run_state": {"claude_subscription_user_id": 1}}),
            ("owner_in_inference_state", {"inference_state": {"claude_subscription_user_id": 1}}),
            ("unknown_mode", {"inference_state": {"claude_model_access": "free"}}),
            ("api_key_mode", {"inference_state": {"claude_model_access": "own-key"}}),
        ]
    )
    def test_inference_keys_outside_a_valid_inference_state_create_nothing(
        self, _name: str, overrides: dict[str, Any]
    ) -> None:
        with self.assertRaises(ValueError):
            self._create(**overrides)

        assert not Task.objects.filter(team_id=self.team.id).exists()

    @parameterized.expand(
        [
            ("replaced_by_posthog_credits", {}, "posthog-gateway", False),
            ("kept_when_not_stated", None, "own-subscription", True),
        ]
    )
    def test_resume_inference_mode_follows_the_new_decision_and_the_new_caller(
        self, _name: str, inference_state: dict[str, Any] | None, access: str, has_owner: bool
    ) -> None:
        created = self._create(
            inference_state={"claude_model_access": "own-subscription", "claude_subscription_source": "server"}
        )
        assert created.run is not None
        self._finish(created.run.id)
        other_member = User.objects.create_and_join(self.organization, "other@example.com", "password")

        with patch("products.tasks.backend.facade.api._trigger_task_processing_workflow", return_value=None):
            successor = self._resume(created, user_id=other_member.id, inference_state=inference_state)

        state = TaskRun.objects.get(id=successor.id).state
        assert state["claude_model_access"] == access
        assert state.get("claude_subscription_user_id") == (other_member.id if has_owner else None)

    @parameterized.expand(
        [
            (
                "stored_subscription",
                {"claude_model_access": "own-subscription", "claude_subscription_source": "server"},
                True,
            ),
            ("relayed_subscription", {"claude_model_access": "own-subscription"}, False),
            ("posthog_credits", {}, True),
        ]
    )
    def test_scheduled_run_is_allowed_unless_its_credential_needs_a_client(
        self, _name: str, inference_state: dict[str, Any], allowed: bool
    ) -> None:
        created = self._create()
        assert created.run is not None
        self._finish(created.run.id)
        task = Task.objects.get(id=created.task_id)

        with patch("products.tasks.backend.facade.api._trigger_task_processing_workflow", return_value=None):
            result = facade._run_resolved_task(
                task,
                self.team.id,
                self.user.id,
                validated_data={"mode": "background", "scheduled_at": timezone.now() + timedelta(days=1)},
                server_run_state=inference_state,
            )

        assert result is not None
        if allowed:
            assert result.error is None
            assert result.run_id is not None
            assert TaskRun.objects.get(id=result.run_id).state.get("claude_model_access") == inference_state.get(
                "claude_model_access"
            )
        else:
            assert result.error is not None
            assert result.error.detail == "Scheduled runs must use the PostHog gateway."
            assert task.runs.count() == 1

    def test_resume_of_an_active_run_is_refused(self) -> None:
        created = self._create()

        with self.assertRaises(cloud_agents.CloudAgentRunNotResumable):
            self._resume(created)

        assert TaskRun.objects.filter(task_id=created.task_id).count() == 1

    def test_resume_of_a_run_of_another_task_is_refused(self) -> None:
        created = self._create()
        other = self._create()
        assert created.run is not None and other.run is not None
        self._finish(other.run.id)

        with self.assertRaises(cloud_agents.CloudAgentRunNotResumable):
            self._resume(created, previous_run_id=other.run.id)

    def test_resume_does_not_find_a_task_of_another_origin(self) -> None:
        other = facade.create_and_run_task(
            team=self.team,
            title="t",
            description="d",
            origin_product=facade.TaskOriginProduct.USER_CREATED,
            user_id=self.user.id,
            repository="posthog/posthog",
        )
        assert other.latest_run is not None
        self._finish(other.latest_run.id)

        with self.assertRaises(cloud_agents.CloudAgentTaskNotFound):
            cloud_agents.resume_cloud_agent_task(
                team_id=self.team.id,
                task_id=other.task_id,
                user_id=self.user.id,
                previous_run_id=other.latest_run.id,
                message="m",
                sandbox_size=DEFAULT_SANDBOX_SIZE,
                model=None,
                reasoning_effort=None,
                inactivity_timeout_seconds=None,
                extra_run_state=None,
            )

    def test_active_run_count_and_run_read_are_scoped_to_the_origin(self) -> None:
        first = self._create()
        second = self._create()
        other = facade.create_and_run_task(
            team=self.team,
            title="t",
            description="d",
            origin_product=facade.TaskOriginProduct.USER_CREATED,
            user_id=self.user.id,
            repository="posthog/posthog",
        )
        assert first.run is not None and second.run is not None and other.latest_run is not None

        assert cloud_agents.count_active_cloud_agent_runs(team_id=self.team.id) == 2
        self._finish(second.run.id, TaskRun.Status.FAILED)
        TaskRun.objects.filter(id=first.run.id).update(status=TaskRun.Status.IN_PROGRESS)
        assert cloud_agents.count_active_cloud_agent_runs(team_id=self.team.id) == 1

        found = cloud_agents.get_cloud_agent_task_run(team_id=self.team.id, run_id=first.run.id)
        assert found is not None and found.id == first.run.id
        assert cloud_agents.get_cloud_agent_task_run(team_id=self.team.id, run_id=other.latest_run.id) is None
        assert cloud_agents.get_cloud_agent_task_run(team_id=self.team.id + 1, run_id=first.run.id) is None
        assert cloud_agents.list_cloud_agent_task_run_ids(team_id=self.team.id, task_id=other.task_id) == []

    def test_plain_task_keeps_the_burstable_default_and_names_no_size(self) -> None:
        created = facade.create_and_run_task(
            team=self.team,
            title="t",
            description="d",
            origin_product=facade.TaskOriginProduct.USER_CREATED,
            user_id=self.user.id,
            repository="posthog/posthog",
        )

        assert created.latest_run is not None
        state = created.latest_run.state
        assert "sandbox_size" not in state
        assert "burstable_sandbox_resources_enabled" not in state
        assert "end_run_when_done" not in state
        assert _is_burstable_sandbox_resources_enabled(run_id=str(created.latest_run.id), state=state) is True
        assert Task.objects.get(id=created.task_id).client_provenance is None


class TestCloudAgentTaskReads(BaseTest):
    def _task(self, *, team: Any = None, billable: bool = True, origin: str = Task.OriginProduct.CLOUD_AGENTS) -> Task:
        return Task.objects.create(
            team=team or self.team,
            created_by=self.user,
            title="Fix the flaky test",
            description="Fix the flaky test",
            origin_product=origin,
            internal=True,
            client_provenance=TaskClientProvenance.CLOUD_AGENTS if billable else None,
        )

    def _run(self, task: Task, status: str = TaskRun.Status.QUEUED, **fields: Any) -> TaskRun:
        return TaskRun.objects.create(
            task=task, team=task.team, status=status, environment=TaskRun.Environment.CLOUD, **fields
        )

    def _session(self, run: TaskRun, sandbox_id: str, started_at: Any, *, hours: int | None = 1) -> SandboxSession:
        return SandboxSession.objects.for_team(run.team_id).create(
            team=run.team,
            task_run=run,
            sandbox_id=sandbox_id,
            origin_product=run.task.origin_product,
            client_provenance=run.task.client_provenance,
            cpu_cores=4,
            memory_gb=16,
            ttl_seconds=6 * 3600,
            created_at=started_at,
            ttl_expires_at=started_at + timedelta(hours=6),
            user_attributed_at=started_at,
            ended_at=started_at + timedelta(hours=hours) if hours is not None else None,
        )

    def _state(self, task: Task) -> contracts.CloudAgentTaskStateDTO:
        return cloud_agents.get_cloud_agent_task_states(team_id=self.team.id, task_ids=[task.id])[task.id]

    def test_state_follows_the_latest_run_and_keeps_the_results_of_earlier_runs(self) -> None:
        start = timezone.now() - timedelta(hours=5)
        task = self._task()
        first = self._run(task, created_at=start)

        waiting = self._state(task)
        assert (waiting.status, waiting.run_end, waiting.current_task_run_id) == ("queued", None, first.id)
        assert (waiting.started_at, waiting.completed_at, waiting.pr_urls, waiting.summary) == (None, None, (), None)
        assert [(s.index, s.task_run_id, s.status, s.started_at, s.ended_at) for s in waiting.sessions] == [
            (1, first.id, "queued", None, None)
        ]

        sandbox_started_at = start + timedelta(minutes=2)
        self._session(first, "sb-1", sandbox_started_at)
        ended_at = start + timedelta(hours=1)
        TaskRun.objects.filter(id=first.id).update(
            status=TaskRun.Status.FAILED,
            completed_at=ended_at,
            state={"timed_out_wall_clock": True, "task_summary": " Fixed half of it. "},
            output={"pr_url": "https://github.com/acme/app/pull/7"},
        )

        stopped = self._state(task)
        assert (stopped.status, stopped.run_end) == ("failed", "timeout")
        assert (stopped.started_at, stopped.completed_at) == (sandbox_started_at, ended_at)
        assert (stopped.pr_url, stopped.summary) == ("https://github.com/acme/app/pull/7", "Fixed half of it.")

        second = self._run(task, created_at=start + timedelta(hours=2))
        resumed = self._state(task)
        assert (resumed.status, resumed.run_end, resumed.current_task_run_id) == ("queued", None, second.id)
        # The task is active again, and it keeps the start time and the results of its first run.
        assert (resumed.started_at, resumed.completed_at) == (sandbox_started_at, None)
        assert (resumed.pr_urls, resumed.summary) == (("https://github.com/acme/app/pull/7",), "Fixed half of it.")
        assert [(s.index, s.status, s.ended_at) for s in resumed.sessions] == [
            (1, "failed", ended_at),
            (2, "queued", None),
        ]

        TaskRun.objects.filter(id=second.id).update(
            status=TaskRun.Status.CANCELLED,
            completed_at=start + timedelta(hours=3),
            state={"cancel_source": "cloud_agents_quota_sweep"},
            output={"pr_url": "https://github.com/acme/app/pull/8"},
        )
        cancelled = self._state(task)
        assert (cancelled.status, cancelled.run_end, cancelled.cancel_source) == (
            "cancelled",
            "cancelled",
            "cloud_agents_quota_sweep",
        )
        assert cancelled.pr_url == "https://github.com/acme/app/pull/8"
        assert cancelled.pr_urls == ("https://github.com/acme/app/pull/7", "https://github.com/acme/app/pull/8")
        # The second run left the queue with no sandbox on record, so its own creation time is its start.
        assert cancelled.sessions[1].started_at == second.created_at

    @parameterized.expand(
        [
            ("no_output", None, {}, [(PR_A, "open"), (PR_B, None)], False, {"answer": "first"}),
            (
                "state_from_the_webhook",
                {"pr_url": PR_A, "pr_state": "closed"},
                {},
                [(PR_A, "closed"), (PR_B, None)],
                False,
                {"answer": "first"},
            ),
            (
                "merged_flag",
                {"pr_url": PR_A, "pr_merged": True},
                {},
                [(PR_A, "merged"), (PR_B, None)],
                False,
                {"answer": "first"},
            ),
            (
                "unknown_state_text",
                {"pr_url": PR_A, "pr_state": "weird"},
                {},
                [(PR_A, "open"), (PR_B, None)],
                False,
                {"answer": "first"},
            ),
            (
                "new_primary_pull_request",
                {"pr_url": PR_B, "pr_state": "draft"},
                {},
                [(PR_A, "open"), (PR_B, "draft")],
                False,
                {"answer": "first"},
            ),
            (
                "new_result_and_the_fields_that_tasks_writes",
                {"answer": "second", "final_message": "Done", "pr_summaries": {}, "ci_status": "passing"},
                {},
                [(PR_A, "open"), (PR_B, None)],
                False,
                {"answer": "second"},
            ),
            (
                "waived",
                None,
                {COMPUTE_WAIVED_REASON_STATE_KEY: "SandboxProvisionError"},
                [(PR_A, "open"), (PR_B, None)],
                True,
                {"answer": "first"},
            ),
        ]
    )
    def test_state_reports_pull_request_states_the_waiver_and_the_agent_result(
        self,
        _name: str,
        latest_output: dict[str, Any] | None,
        latest_state: dict[str, Any],
        pull_requests: list[tuple[str, str | None]],
        waived: bool,
        structured_output: dict[str, Any],
    ) -> None:
        start = timezone.now() - timedelta(hours=2)
        task = self._task()
        self._run(
            task,
            TaskRun.Status.COMPLETED,
            created_at=start,
            output={"pr_url": PR_A, "pr_urls": [PR_A, PR_B], "pr_state": "open", "answer": "first"},
            # A waiver of an earlier run does not describe the latest run.
            state={COMPUTE_WAIVED_REASON_STATE_KEY: "SandboxProvisionError"} if not waived else {},
        )
        self._run(
            task, TaskRun.Status.FAILED, created_at=start + timedelta(hours=1), output=latest_output, state=latest_state
        )

        state = self._state(task)

        assert [(pull_request.url, pull_request.state) for pull_request in state.pull_requests] == pull_requests
        assert state.compute_waived is waived
        assert state.structured_output == structured_output

    def test_reads_do_not_find_a_task_of_another_origin_or_another_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        mine = self._task()
        other_origin = self._task(origin=Task.OriginProduct.USER_CREATED)
        other_team_task = self._task(team=other_team)
        unknown = uuid4()
        for task in (mine, other_origin, other_team_task):
            run = self._run(task, TaskRun.Status.COMPLETED, completed_at=timezone.now())
            self._session(run, f"sb-{task.id}", timezone.now() - timedelta(hours=3))
        task_ids = [mine.id, other_origin.id, other_team_task.id, unknown]

        states = cloud_agents.get_cloud_agent_task_states(team_id=self.team.id, task_ids=task_ids)
        billing = cloud_agents.get_cloud_agent_tasks_billing(team_id=self.team.id, task_ids=task_ids)

        assert {task_id: (state.status, len(state.sessions)) for task_id, state in states.items()} == {
            mine.id: ("completed", 1),
            other_origin.id: ("queued", 0),
            other_team_task.id: ("queued", 0),
            unknown: ("queued", 0),
        }
        assert {task_id: charges.compute_cost_cents for task_id, charges in billing.items()} == {
            mine.id: 37,
            other_origin.id: None,
            other_team_task.id: None,
            unknown: None,
        }
        assert billing[mine.id] == get_task_run_billing(team_id=self.team.id, task_id=mine.id)
        assert cloud_agents.list_cloud_agent_task_ids(team_id=self.team.id, statuses=["completed"], limit=10) == [
            mine.id
        ]
        usage = cloud_agents.summarize_cloud_agent_usage(
            team_id=self.team.id,
            date_from=timezone.now() - timedelta(days=1),
            date_to=timezone.now() + timedelta(days=1),
            limit=10,
        )
        assert [row.task_id for row in usage.rows] == [mine.id]

    def test_status_filter_reads_the_latest_run_of_each_task_newest_first(self) -> None:
        now = timezone.now()
        resumed, failed, running, no_run, deleted = (self._task() for _ in range(5))
        Task.objects.filter(id=deleted.id).update(deleted=True)
        for age, task in enumerate([deleted, no_run, running, failed, resumed]):
            Task.objects.filter(id=task.id).update(created_at=now - timedelta(minutes=age))
        self._run(resumed, TaskRun.Status.FAILED, created_at=now - timedelta(hours=2))
        self._run(resumed, TaskRun.Status.QUEUED, created_at=now - timedelta(hours=1))
        self._run(failed, TaskRun.Status.FAILED)
        self._run(running, TaskRun.Status.IN_PROGRESS)
        self._run(deleted, TaskRun.Status.FAILED)

        def listed(statuses: list[str], limit: int = 10) -> list[Any]:
            return cloud_agents.list_cloud_agent_task_ids(team_id=self.team.id, statuses=statuses, limit=limit)

        assert listed(["failed"]) == [deleted.id, failed.id]
        assert listed(["not_started", "queued"]) == [no_run.id, resumed.id]
        assert listed(["failed", "in_progress"], limit=2) == [deleted.id, running.id]
        assert listed(["completed"]) == []
        # A time range moves the limit to the tasks of that range.
        assert cloud_agents.list_cloud_agent_task_ids(
            team_id=self.team.id,
            statuses=["failed", "in_progress"],
            limit=1,
            created_after=now - timedelta(minutes=3),
            created_before=now - timedelta(seconds=30),
        ) == [running.id]

    def test_active_billable_runs_are_the_runs_that_a_quota_sweep_stops(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        now = timezone.now()
        billed = self._task()
        older = self._run(billed, TaskRun.Status.IN_PROGRESS, created_at=now - timedelta(minutes=5))
        waiting = self._run(self._task(), TaskRun.Status.NOT_STARTED, created_at=now - timedelta(minutes=1))
        self._run(self._task(), TaskRun.Status.COMPLETED)
        self._run(self._task(billable=False), TaskRun.Status.IN_PROGRESS)
        self._run(self._task(origin=Task.OriginProduct.USER_CREATED), TaskRun.Status.IN_PROGRESS)
        self._run(self._task(team=other_team), TaskRun.Status.IN_PROGRESS)

        active = cloud_agents.list_active_billable_cloud_agent_runs(team_id=self.team.id, limit=10)

        assert [(run.task_id, run.task_run_id) for run in active] == [
            (billed.id, older.id),
            (waiting.task_id, waiting.id),
        ]
        assert cloud_agents.list_active_billable_cloud_agent_runs(team_id=self.team.id, limit=1) == active[:1]

    def test_usage_summary_has_one_row_for_each_task_of_the_period_up_to_its_limit(self) -> None:
        now = timezone.now()
        tasks = [self._task() for _ in range(3)]
        for age_days, task in enumerate(tasks):
            Task.objects.filter(id=task.id).update(created_at=now - timedelta(days=age_days, hours=1))
            run = self._run(task, TaskRun.Status.COMPLETED, completed_at=now)
            for index in range(age_days + 1):
                self._session(run, f"sb-{task.id}-{index}", now - timedelta(hours=5))

        def summarize(days: int, limit: int) -> contracts.CloudAgentUsageDTO:
            return cloud_agents.summarize_cloud_agent_usage(
                team_id=self.team.id, date_from=now - timedelta(days=days), date_to=now, limit=limit
            )

        everything = summarize(days=3, limit=10)
        assert [(row.task_id, row.compute_cost_cents, row.vcpu_seconds) for row in everything.rows] == [
            (tasks[0].id, 37, Decimal(14_400)),
            (tasks[1].id, 74, Decimal(28_800)),
            (tasks[2].id, 110, Decimal(43_200)),
        ]
        assert everything.truncated is False
        assert [row.task_id for row in summarize(days=2, limit=10).rows] == [tasks[0].id, tasks[1].id]
        newest = summarize(days=3, limit=2)
        assert ([row.task_id for row in newest.rows], newest.truncated) == ([tasks[0].id, tasks[1].id], True)

    @parameterized.expand([("few_tasks", 3), ("a_page_of_tasks", 50)])
    def test_each_read_makes_the_same_number_of_queries_for_any_number_of_tasks(self, _name: str, count: int) -> None:
        now = timezone.now()
        tasks = [self._task() for _ in range(count)]
        for index, task in enumerate(tasks):
            first = self._run(task, TaskRun.Status.FAILED, completed_at=now, created_at=now - timedelta(hours=2))
            self._run(task, TaskRun.Status.IN_PROGRESS)
            self._session(first, f"sb-{index}", now - timedelta(hours=5))
        task_ids = [task.id for task in tasks]

        # The runs, the team that scopes the sandbox sessions, and the sandbox sessions.
        with self.assertNumQueries(3):
            states = cloud_agents.get_cloud_agent_task_states(team_id=self.team.id, task_ids=task_ids)
        with self.assertNumQueries(3):
            billing = cloud_agents.get_cloud_agent_tasks_billing(team_id=self.team.id, task_ids=task_ids)
        with self.assertNumQueries(1):
            listed = cloud_agents.list_cloud_agent_task_ids(team_id=self.team.id, statuses=["in_progress"], limit=count)
        with self.assertNumQueries(1):
            active = cloud_agents.list_active_billable_cloud_agent_runs(team_id=self.team.id, limit=count)
        # The tasks of the period, then the same three queries as the charges.
        with self.assertNumQueries(4):
            usage = cloud_agents.summarize_cloud_agent_usage(
                team_id=self.team.id, date_from=now - timedelta(days=1), date_to=now + timedelta(days=1), limit=count
            )

        assert {len(state.sessions) for state in states.values()} == {2}
        assert {charges.compute_cost_cents for charges in billing.values()} == {37}
        assert len(states) == len(billing) == len(listed) == len(active) == len(usage.rows) == count
