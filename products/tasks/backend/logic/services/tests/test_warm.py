from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework.exceptions import PermissionDenied, Throttled

from posthog.exceptions import QuotaLimitExceeded

from products.tasks.backend.logic.services.warm import SandboxWarmer
from products.tasks.backend.models import Task, TaskRun

WARM = "products.tasks.backend.logic.services.warm"
_CAPS = SandboxWarmer.ORIGIN_PRODUCT_CAPS[Task.OriginProduct.POSTHOG_AI]


class TestSandboxWarmerWarm(APIBaseTest):
    def _task(self, *, origin=Task.OriginProduct.POSTHOG_AI, created_by=None) -> Task:
        return Task.objects.create(
            team=self.team,
            title="",
            description="",
            origin_product=origin,
            created_by=created_by or self.user,
        )

    def _warm_run_on_new_task(self, *, created_by=None) -> TaskRun:
        task = self._task(created_by=created_by)
        return task.create_run(mode="interactive", extra_state={"await_user_message": True})

    def test_provisions_warm_run_when_task_has_no_runs(self):
        task = self._task()
        with (
            patch(f"{WARM}.execute_task_processing_workflow") as m_workflow,
            patch(f"{WARM}.is_team_limited", return_value=False),
            self.captureOnCommitCallbacks(execute=True),
        ):
            result = SandboxWarmer(task, user=self.user).warm(extra_state={"systemPrompt": "SYS"})

        assert result.just_created is True
        run = result.run
        assert run.state["await_user_message"] is True
        assert run.state["initial_permission_mode"] == "default"
        assert run.state["systemPrompt"] == "SYS"
        assert run.state["mode"] == "interactive"
        assert "resume_from_run_id" not in run.state

        m_workflow.assert_called_once()
        _, kwargs = m_workflow.call_args
        assert kwargs["run_id"] == str(run.id)
        assert kwargs["create_pr"] is False
        assert kwargs["posthog_mcp_scopes"] == "full"

    def test_idempotent_when_non_terminal_run_exists(self):
        task = self._task()
        existing = task.create_run(mode="interactive", extra_state={"await_user_message": True})

        with (
            patch(f"{WARM}.execute_task_processing_workflow") as m_workflow,
            patch(f"{WARM}.is_team_limited", return_value=False),
            self.captureOnCommitCallbacks(execute=True),
        ):
            result = SandboxWarmer(task, user=self.user).warm()

        assert result.just_created is False
        assert result.run.id == existing.id
        assert task.runs.count() == 1
        m_workflow.assert_not_called()

    def test_rewarms_with_resume_after_terminal_run(self):
        task = self._task()
        terminal = task.create_run(mode="interactive", extra_state={"snapshot_external_id": "snap-1"})
        terminal.status = TaskRun.Status.COMPLETED
        terminal.save(update_fields=["status"])

        with (
            patch(f"{WARM}.execute_task_processing_workflow") as m_workflow,
            patch(f"{WARM}.is_team_limited", return_value=False),
            self.captureOnCommitCallbacks(execute=True),
        ):
            result = SandboxWarmer(task, user=self.user).warm()

        assert result.just_created is True
        assert result.run.id != terminal.id
        assert result.run.state["await_user_message"] is True
        assert result.run.state["resume_from_run_id"] == str(terminal.id)
        # Snapshot carried forward so the warm session reuses the prior Run's filesystem.
        assert result.run.state["snapshot_external_id"] == "snap-1"
        m_workflow.assert_called_once()

    def test_dispatch_is_deferred_to_commit(self):
        # No captureOnCommitCallbacks: the test transaction never commits, so the on_commit dispatch
        # must not fire — proving provisioning isn't done inside the atomic block.
        task = self._task()
        with (
            patch(f"{WARM}.execute_task_processing_workflow") as m_workflow,
            patch(f"{WARM}.is_team_limited", return_value=False),
        ):
            result = SandboxWarmer(task, user=self.user).warm()
            m_workflow.assert_not_called()

        assert result.just_created is True
        assert task.runs.count() == 1

    def test_over_quota_raises_and_creates_no_run(self):
        task = self._task()
        with (
            patch(f"{WARM}.execute_task_processing_workflow") as m_workflow,
            patch(f"{WARM}.is_team_limited", return_value=True),
        ):
            with self.assertRaises(QuotaLimitExceeded):
                SandboxWarmer(task, user=self.user).warm()

        assert task.runs.count() == 0
        m_workflow.assert_not_called()

    def test_unregistered_origin_product_is_rejected(self):
        # Fail-closed: only origin products with a registered quota gate may warm.
        task = self._task(origin=Task.OriginProduct.ERROR_TRACKING)
        with self.assertRaises(PermissionDenied):
            SandboxWarmer(task, user=self.user).warm()
        assert task.runs.count() == 0

    def test_over_cap_raises_throttled(self):
        for _ in range(_CAPS.per_user):
            self._warm_run_on_new_task()

        task = self._task()
        with (
            patch(f"{WARM}.execute_task_processing_workflow") as m_workflow,
            patch(f"{WARM}.is_team_limited", return_value=False),
        ):
            with self.assertRaises(Throttled):
                SandboxWarmer(task, user=self.user).warm()

        assert task.runs.count() == 0
        m_workflow.assert_not_called()


class TestSandboxWarmerAtCapacity(APIBaseTest):
    def _warm_run_on_new_task(self, *, created_by=None, status=TaskRun.Status.QUEUED, warm=True) -> TaskRun:
        task = Task.objects.create(
            team=self.team,
            title="",
            description="",
            origin_product=Task.OriginProduct.POSTHOG_AI,
            created_by=created_by or self.user,
        )
        extra = {"await_user_message": True} if warm else {}
        run = task.create_run(mode="interactive", extra_state=extra)
        if status != TaskRun.Status.QUEUED:
            run.status = status
            run.save(update_fields=["status"])
        return run

    def test_counts_only_warm_non_terminal_runs(self):
        origin = Task.OriginProduct.POSTHOG_AI

        # Terminal warm runs drop from the count via the status filter.
        for _ in range(_CAPS.per_user):
            self._warm_run_on_new_task(status=TaskRun.Status.CANCELLED)
        assert SandboxWarmer.at_capacity(origin, self.team, self.user) is False

        # Activated (await_user_message cleared) non-terminal runs drop via the state filter.
        for _ in range(_CAPS.per_user):
            self._warm_run_on_new_task(warm=False)
        assert SandboxWarmer.at_capacity(origin, self.team, self.user) is False

        # Genuine warm runs do count.
        for _ in range(_CAPS.per_user):
            self._warm_run_on_new_task()
        assert SandboxWarmer.at_capacity(origin, self.team, self.user) is True

    def test_per_org_cap_counts_across_users(self):
        origin = Task.OriginProduct.POSTHOG_AI
        other = self._create_user("warmer@posthog.com")
        for _ in range(_CAPS.per_org):
            self._warm_run_on_new_task(created_by=other)

        # The requesting user holds no warm runs, but the org cap is full.
        assert SandboxWarmer.at_capacity(origin, self.team, self.user) is True
