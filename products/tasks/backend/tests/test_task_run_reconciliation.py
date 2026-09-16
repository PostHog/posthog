from datetime import timedelta

from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone as django_timezone

from parameterized import parameterized

from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.tasks.backend.models import Task, TaskRun
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
    ) -> TaskRun:
        task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="A task",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        run = task.create_run(mode="background", environment=environment)
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
