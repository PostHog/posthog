from unittest.mock import patch

from django.test import TestCase

from posthog.models import Organization, Team, User

from products.tasks.backend.automation_service import run_task_automation, update_automation_run_result
from products.tasks.backend.models import Task, TaskAutomation, TaskRun


class TestAutomationService(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_user(email="test@example.com", first_name="Test", password="password")

    def create_automation(self) -> TaskAutomation:
        task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Daily PRs",
            description="Check my GitHub PRs",
            origin_product=Task.OriginProduct.AUTOMATION,
            repository="posthog/posthog",
        )
        return TaskAutomation.objects.create(
            task=task,
            cron_expression="0 9 * * *",
            timezone="Europe/London",
            enabled=True,
        )

    @patch("products.tasks.backend.automation_service.execute_task_processing_workflow_for_automation")
    def test_run_task_automation_is_idempotent_per_trigger_workflow(self, mock_execute_workflow):
        automation = self.create_automation()

        with self.captureOnCommitCallbacks(execute=True):
            first_task, first_run = run_task_automation(
                str(automation.id), trigger_workflow_id="automation-workflow-123"
            )
        with self.captureOnCommitCallbacks(execute=True):
            second_task, second_run = run_task_automation(
                str(automation.id), trigger_workflow_id="automation-workflow-123"
            )

        self.assertEqual(first_task.id, second_task.id)
        self.assertEqual(first_run.id, second_run.id)
        self.assertEqual(Task.objects.filter(origin_product=Task.OriginProduct.AUTOMATION).count(), 1)
        self.assertEqual(TaskRun.objects.filter(task__origin_product=Task.OriginProduct.AUTOMATION).count(), 1)
        self.assertEqual(first_run.state["automation_id"], str(automation.id))
        self.assertEqual(first_run.state["automation_trigger_workflow_id"], "automation-workflow-123")
        self.assertEqual(mock_execute_workflow.call_count, 2)

    @patch("products.tasks.backend.automation_service.execute_task_processing_workflow_for_automation")
    def test_run_task_automation_does_not_reuse_run_from_another_team(self, mock_execute_workflow):
        automation = self.create_automation()
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        other_task = Task.objects.create(
            team=other_team,
            created_by=self.user,
            title="Other automation",
            description="Should not be reused",
            origin_product=Task.OriginProduct.AUTOMATION,
            repository="posthog/posthog",
        )
        other_run = other_task.create_run(
            mode="background",
            extra_state={
                "automation_id": str(automation.id),
                "automation_trigger_workflow_id": "automation-workflow-123",
            },
        )

        with self.captureOnCommitCallbacks(execute=True):
            task, task_run = run_task_automation(str(automation.id), trigger_workflow_id="automation-workflow-123")

        self.assertNotEqual(task_run.id, other_run.id)
        self.assertEqual(task.team_id, self.team.id)
        self.assertEqual(task_run.task_id, task.id)
        self.assertEqual(mock_execute_workflow.call_count, 1)

    @patch("products.tasks.backend.automation_service.execute_task_processing_workflow_for_automation")
    def test_run_task_automation_reuses_task_and_creates_new_runs(self, mock_execute_workflow):
        automation = self.create_automation()

        with self.captureOnCommitCallbacks(execute=True):
            first_task, first_run = run_task_automation(str(automation.id))
        with self.captureOnCommitCallbacks(execute=True):
            second_task, second_run = run_task_automation(str(automation.id))

        automation.refresh_from_db()
        self.assertEqual(first_task.id, second_task.id)
        self.assertEqual(automation.task_id, first_task.id)
        self.assertEqual(automation.last_run_at, second_run.created_at)
        self.assertEqual(automation.last_run_status, TaskAutomation.RunStatus.RUNNING)
        self.assertNotEqual(first_run.id, second_run.id)
        self.assertEqual(Task.objects.filter(origin_product=Task.OriginProduct.AUTOMATION).count(), 1)
        self.assertEqual(TaskRun.objects.filter(task=first_task).count(), 2)
        self.assertEqual(mock_execute_workflow.call_count, 2)

    def test_automation_last_run_properties_come_from_last_task_run(self):
        automation = self.create_automation()
        task_run = automation.task.create_run(mode="background", extra_state={"automation_id": str(automation.id)})
        task_run.status = TaskRun.Status.COMPLETED
        task_run.save(update_fields=["status", "updated_at"])

        automation.last_task_run = task_run
        automation.save(update_fields=["last_task_run", "updated_at"])

        automation.refresh_from_db()
        self.assertEqual(automation.last_run_at, task_run.created_at)
        self.assertEqual(automation.last_run_status, TaskAutomation.RunStatus.SUCCESS)

    def test_update_automation_run_result_records_failure_from_previous_run(self):
        automation = self.create_automation()
        first_run = automation.task.create_run(mode="background", extra_state={"automation_id": str(automation.id)})
        second_run = automation.task.create_run(mode="background", extra_state={"automation_id": str(automation.id)})

        automation.last_task_run = second_run
        automation.save(update_fields=["last_task_run", "updated_at"])

        first_run.status = TaskRun.Status.FAILED
        first_run.error_message = "Automation failed after a newer run started"
        first_run.save(update_fields=["status", "error_message", "updated_at"])

        update_automation_run_result(first_run)

        automation.refresh_from_db()
        self.assertEqual(automation.last_task_run_id, second_run.id)
        self.assertEqual(automation.last_error, "Automation failed after a newer run started")
