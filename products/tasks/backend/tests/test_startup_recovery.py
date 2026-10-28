from datetime import timedelta
from functools import partial

import time_machine
from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from products.tasks.backend.facade.api import latest_agent_startup_success
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.start_agent_server import (
    _record_agent_startup_attempt,
    _record_agent_startup_success,
)


class TestAgentStartupRecovery(BaseTest):
    @parameterized.expand(
        [
            ("acp", None, "claude", TaskRun.Status.IN_PROGRESS),
            ("acp", "codex", "codex", TaskRun.Status.IN_PROGRESS),
            ("pi", None, "pi", TaskRun.Status.IN_PROGRESS),
            ("acp", None, "claude", TaskRun.Status.FAILED),
            ("acp", None, "claude", TaskRun.Status.CANCELLED),
            ("acp", None, "claude", TaskRun.Status.COMPLETED),
        ]
    )
    def test_only_a_completed_worker_attempt_is_recovery_evidence(
        self, runtime: str, adapter: str | None, provider: str, final_status: str
    ) -> None:
        task = Task.objects.create(team=self.team, title="Example research", repository="example/research")
        run = TaskRun.objects.create(team=self.team, task=task)
        context = TaskProcessingContext(
            task_id=str(task.id),
            run_id=str(run.id),
            team_id=self.team.id,
            team_uuid=str(self.team.uuid),
            organization_id=str(self.organization.id),
            github_integration_id=None,
            repository=task.repository,
            distinct_id="example",
            task_runtime=runtime,
            state={"runtime_adapter": adapter} if adapter else {},
        )
        latest_startup = partial(
            latest_agent_startup_success,
            team_id=self.team.id,
            repository="example/research",
            provider=provider,
            runtime="gvisor",
        )
        started_at = timezone.now()
        with time_machine.travel(started_at, tick=False):
            _record_agent_startup_attempt(context, "gvisor")
        run.refresh_from_db()
        assert "agent_startup_success" not in run.state
        assert latest_startup() is None
        with time_machine.travel(started_at + timedelta(seconds=1), tick=False):
            _record_agent_startup_success(context)
        run.refresh_from_db()
        success = run.state["agent_startup_success"]
        assert success["started_at"] == started_at.isoformat()
        assert success["provider"] == provider
        assert latest_startup() == started_at
        with time_machine.travel(started_at + timedelta(seconds=2), tick=False):
            _record_agent_startup_attempt(context, "gvisor")
        run.refresh_from_db()
        assert run.state["agent_startup_success"] == success
        assert latest_startup() == started_at
        TaskRun.update_state_atomic(str(run.id), updates={"startup_failure": {"reason": "proxy_invalid"}})
        TaskRun.objects.filter(id=run.id).update(error_message="Turn failed", status=final_status)
        with time_machine.travel(started_at + timedelta(seconds=3), tick=False):
            _record_agent_startup_success(context)
        run.refresh_from_db()
        assert "startup_failure" not in run.state
        assert run.error_message == ("Turn failed" if run.is_terminal else None)
        assert run.state["agent_startup_success"]["started_at"] == (started_at + timedelta(seconds=2)).isoformat()
        assert latest_startup() == started_at + timedelta(seconds=2)
