from datetime import timedelta

from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone as django_timezone

from celery.exceptions import SoftTimeLimitExceeded
from parameterized import parameterized

from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.tasks.backend.models import Loop, Task, TaskRun
from products.tasks.backend.task_run_reconciliation import (
    REAP_MESSAGE,
    STALE_AFTER,
    reconcile_stale_in_progress_task_runs,
)


class TestReconcileStaleInProgressTaskRuns(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_user(email="run-owner@example.com", first_name="Run", password="password")
        self.organization.members.add(self.user)

    def create_run(
        self,
        *,
        status=TaskRun.Status.IN_PROGRESS,
        environment=TaskRun.Environment.CLOUD,
        age=None,
        extra_state=None,
    ) -> TaskRun:
        task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="A task",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        run = task.create_run(mode="background", environment=environment, extra_state=extra_state)
        run.status = status
        run.save(update_fields=["status", "updated_at"])
        if age is not None:
            # auto_now pins updated_at to now on save, so age it with a bare update().
            TaskRun.objects.filter(id=run.id).update(updated_at=django_timezone.now() - age)
        return run

    def reconcile(self, liveness: str) -> dict[str, int]:
        with patch(
            "products.tasks.backend.temporal.client.describe_task_run_workflow_liveness",
            side_effect=lambda workflow_ids: dict.fromkeys(workflow_ids, liveness),
        ):
            return reconcile_stale_in_progress_task_runs()

    def test_stranded_run_whose_workflow_is_gone_is_failed(self):
        run = self.create_run(age=STALE_AFTER + timedelta(minutes=1))

        outcomes = self.reconcile("gone")

        run.refresh_from_db()
        self.assertEqual(outcomes.get("reaped"), 1)
        self.assertEqual(run.status, TaskRun.Status.FAILED)
        self.assertIsNotNone(run.completed_at)
        self.assertEqual(run.error_message, REAP_MESSAGE)

    @parameterized.expand(
        [
            # A live orchestrator terminalizes the row itself; killing it closes a user's run under them.
            ("workflow_still_running", "running", "workflow_running"),
            # A Temporal outage must not mass-fail every in-flight run in the deployment.
            ("temporal_cannot_answer", "unknown", "workflow_unknown"),
        ]
    )
    def test_run_is_left_alone_when_workflow_is_not_proven_gone(self, _name, liveness, expected_outcome):
        run = self.create_run(age=STALE_AFTER + timedelta(minutes=1))

        outcomes = self.reconcile(liveness)

        run.refresh_from_db()
        self.assertEqual(outcomes.get(expected_outcome), 1)
        self.assertEqual(run.status, TaskRun.Status.IN_PROGRESS)

    def test_sweep_deadline_is_not_recorded_as_a_per_run_failure(self):
        self.create_run(age=STALE_AFTER + timedelta(minutes=1))

        with patch(
            "products.tasks.backend.facade.api.claim_and_fail_stranded_cloud_run",
            side_effect=SoftTimeLimitExceeded(),
        ):
            # The sweep ran out of time; that is not this run failing to reconcile, and the
            # metric this sweep feeds must not gain a phantom failure for it.
            with self.assertRaises(SoftTimeLimitExceeded):
                self.reconcile("gone")

    def test_reaped_loop_run_drives_loop_bookkeeping(self):
        loop = Loop(
            team=self.team,
            created_by=self.user,
            name="Daily digest",
            instructions="Summarize open PRs across the team's repos",
            runtime_adapter="claude",
            model="claude-sonnet-4-5",
            enabled=True,
        )
        loop.save()
        run = self.create_run(age=STALE_AFTER + timedelta(minutes=1), extra_state={"loop_id": str(loop.id)})

        outcomes = self.reconcile("gone")

        run.refresh_from_db()
        loop.refresh_from_db()
        self.assertEqual(outcomes.get("reaped"), 1)
        self.assertEqual(run.status, TaskRun.Status.FAILED)
        # Without this the loop surface keeps stale state and the auto-pause counter never
        # moves, so a loop whose runs keep dying is never paused.
        self.assertEqual(loop.last_run_status, TaskRun.Status.FAILED)
        self.assertEqual(loop.last_error, REAP_MESSAGE)
        self.assertEqual(loop.consecutive_failures, 1)

    @parameterized.expand(
        [
            # The resume re-queued the run and its replacement workflow has not started yet.
            ("resumed", TaskRun.Status.QUEUED),
            # The replacement workflow already wrote its own IN_PROGRESS, so only the row
            # version separates it from the run that was judged.
            ("resumed_and_restarted", TaskRun.Status.IN_PROGRESS),
        ]
    )
    def test_run_that_moved_between_describe_and_claim_is_left_alone(self, _name, status_after_resume):
        run = self.create_run(age=STALE_AFTER + timedelta(minutes=1))

        def resume_the_run_then_report_gone(workflow_ids):
            # `gone` is the right verdict for the workflow that was described: it closed, which
            # is what let the user resume at all. A resume reuses the same workflow id, so that
            # verdict must not reach the live replacement.
            TaskRun.objects.filter(id=run.id).update(status=status_after_resume, updated_at=django_timezone.now())
            return dict.fromkeys(workflow_ids, "gone")

        with patch(
            "products.tasks.backend.temporal.client.describe_task_run_workflow_liveness",
            side_effect=resume_the_run_then_report_gone,
        ):
            outcomes = reconcile_stale_in_progress_task_runs()

        run.refresh_from_db()
        self.assertEqual(outcomes.get("claim_lost"), 1)
        self.assertEqual(run.status, status_after_resume)
        self.assertIsNone(run.completed_at)

    @parameterized.expand(
        [
            # Inside the staleness window the workflow may simply be mid-model-call.
            ("recently_updated", TaskRun.Status.IN_PROGRESS, TaskRun.Environment.CLOUD, timedelta(minutes=5)),
            # A local run is driven by the desktop and has no cloud workflow to describe.
            (
                "local_environment",
                TaskRun.Status.IN_PROGRESS,
                TaskRun.Environment.LOCAL,
                STALE_AFTER + timedelta(minutes=1),
            ),
            # QUEUED is owned by kill_stale_queued_task_runs, which has its own 24h window.
            ("queued", TaskRun.Status.QUEUED, TaskRun.Environment.CLOUD, STALE_AFTER + timedelta(minutes=1)),
        ]
    )
    def test_run_is_not_a_candidate(self, _name, status, environment, age):
        run = self.create_run(status=status, environment=environment, age=age)

        outcomes = self.reconcile("gone")

        run.refresh_from_db()
        self.assertEqual(outcomes, {})
        self.assertEqual(run.status, status)
