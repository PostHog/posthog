import uuid

from unittest.mock import MagicMock, patch

from django.db import IntegrityError
from django.test import TestCase

from parameterized import parameterized

from posthog.models import Integration, Organization, Team

from products.tasks.backend.lib.templates import DEFAULT_WORKFLOW_TEMPLATE, WorkflowStageTemplate, WorkflowTemplate
from products.tasks.backend.models import SandboxSnapshot, Task, TaskProgress, TaskWorkflow, WorkflowStage


class TestTaskWorkflow(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.workflow = TaskWorkflow.objects.create(
            team=self.team,
            name="Test Workflow",
            description="Test Description",
            color="#3b82f6",
            is_default=False,
            is_active=True,
        )
        self.stage1 = WorkflowStage.objects.create(
            workflow=self.workflow,
            name="Backlog",
            key="backlog",
            position=0,
            color="#6b7280",
        )
        self.stage2 = WorkflowStage.objects.create(
            workflow=self.workflow,
            name="In Progress",
            key="in_progress",
            position=1,
            color="#3b82f6",
        )

    def test_workflow_creation(self):
        workflow = TaskWorkflow.objects.create(
            team=self.team,
            name="New Workflow",
            description="New Description",
        )
        self.assertEqual(workflow.team, self.team)
        self.assertEqual(workflow.name, "New Workflow")
        self.assertEqual(workflow.description, "New Description")
        self.assertEqual(workflow.color, "#3b82f6")
        self.assertFalse(workflow.is_default)
        self.assertTrue(workflow.is_active)
        self.assertEqual(workflow.version, 1)

    def test_str_representation(self):
        self.assertEqual(str(self.workflow), "Test Workflow (Test Team)")

    def test_unique_together_constraint(self):
        with self.assertRaises(IntegrityError):
            TaskWorkflow.objects.create(
                team=self.team,
                name="Test Workflow",
            )

    def test_active_stages_property(self):
        archived_stage = WorkflowStage.objects.create(
            workflow=self.workflow,
            name="Archived",
            key="archived",
            position=2,
            is_archived=True,
        )
        active_stages = self.workflow.active_stages
        self.assertIn(self.stage1, active_stages)
        self.assertIn(self.stage2, active_stages)
        self.assertNotIn(archived_stage, active_stages)

    def test_migrate_tasks_to_workflow(self):
        target_workflow = TaskWorkflow.objects.create(
            team=self.team,
            name="Target Workflow",
        )
        target_stage = WorkflowStage.objects.create(
            workflow=target_workflow,
            name="Backlog",
            key="backlog",
            position=0,
        )

        task1 = Task.objects.create(
            team=self.team,
            title="Task 1",
            description="Description 1",
            origin_product=Task.OriginProduct.USER_CREATED,
            workflow=self.workflow,
            current_stage=self.stage1,
        )
        task2 = Task.objects.create(
            team=self.team,
            title="Task 2",
            description="Description 2",
            origin_product=Task.OriginProduct.USER_CREATED,
            workflow=self.workflow,
            current_stage=self.stage2,
        )

        migrated_count = self.workflow.migrate_tasks_to_workflow(target_workflow)

        self.assertEqual(migrated_count, 2)
        task1.refresh_from_db()
        task2.refresh_from_db()
        self.assertEqual(task1.workflow, target_workflow)
        self.assertEqual(task1.current_stage, target_stage)
        self.assertEqual(task2.workflow, target_workflow)

    def test_migrate_tasks_same_workflow_returns_zero(self):
        result = self.workflow.migrate_tasks_to_workflow(self.workflow)
        self.assertEqual(result, 0)

    def test_migrate_tasks_different_team_raises_error(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        other_workflow = TaskWorkflow.objects.create(team=other_team, name="Other Workflow")

        with self.assertRaises(ValueError) as cm:
            self.workflow.migrate_tasks_to_workflow(other_workflow)
        self.assertEqual(str(cm.exception), "Source and target workflows must belong to the same team")

    def test_unassign_tasks(self):
        task1 = Task.objects.create(
            team=self.team,
            title="Task 1",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
            workflow=self.workflow,
            current_stage=self.stage1,
        )
        task2 = Task.objects.create(
            team=self.team,
            title="Task 2",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
            workflow=self.workflow,
            current_stage=self.stage2,
        )

        self.workflow.unassign_tasks()

        task1.refresh_from_db()
        task2.refresh_from_db()
        self.assertIsNone(task1.workflow)
        self.assertIsNone(task1.current_stage)
        self.assertIsNone(task2.workflow)
        self.assertIsNone(task2.current_stage)

    def test_deactivate_safely(self):
        default_workflow = TaskWorkflow.objects.create(
            team=self.team,
            name="Default Workflow",
            is_default=True,
        )

        WorkflowStage.objects.create(
            workflow=default_workflow,
            name="Default Stage",
            key="default",
            position=0,
        )

        task = Task.objects.create(
            team=self.team,
            title="Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
            workflow=self.workflow,
            current_stage=self.stage1,
        )

        self.workflow.deactivate_safely()

        self.workflow.refresh_from_db()
        self.assertFalse(self.workflow.is_active)

        task.refresh_from_db()
        self.assertEqual(task.workflow, default_workflow)

    def test_deactivate_default_workflow_raises_error(self):
        self.workflow.is_default = True
        self.workflow.save()

        with self.assertRaises(ValueError) as cm:
            self.workflow.deactivate_safely()
        self.assertEqual(str(cm.exception), "Cannot deactivate the default workflow")

    def test_from_template(self):
        template = WorkflowTemplate(
            name="Template Workflow",
            description="Template Description",
            stages=[
                WorkflowStageTemplate(
                    key="todo",
                    name="To Do",
                    color="#ff0000",
                    agent_name=None,
                    is_manual_only=False,
                ),
                WorkflowStageTemplate(
                    key="done",
                    name="Done",
                    color="#00ff00",
                    agent_name=None,
                    is_manual_only=True,
                ),
            ],
        )

        TaskWorkflow.from_template(template, self.team, is_default=True)

        workflow = TaskWorkflow.objects.get(name="Template Workflow", team=self.team)
        self.assertEqual(workflow.description, "Template Description")
        self.assertTrue(workflow.is_default)
        self.assertTrue(workflow.is_active)

        stages = workflow.stages.order_by("position")
        self.assertEqual(stages.count(), 2)
        self.assertEqual(stages[0].key, "todo")
        self.assertEqual(stages[0].name, "To Do")
        self.assertEqual(stages[0].color, "#ff0000")
        self.assertFalse(stages[0].is_manual_only)
        self.assertEqual(stages[1].key, "done")
        self.assertEqual(stages[1].name, "Done")
        self.assertEqual(stages[1].color, "#00ff00")
        self.assertTrue(stages[1].is_manual_only)

    def test_create_default_workflow(self):
        TaskWorkflow.create_default_workflow(self.team)

        workflow = TaskWorkflow.objects.get(name=DEFAULT_WORKFLOW_TEMPLATE.name, team=self.team)
        self.assertTrue(workflow.is_default)
        self.assertTrue(workflow.is_active)
        self.assertEqual(workflow.stages.count(), len(DEFAULT_WORKFLOW_TEMPLATE.stages))


class TestWorkflowStage(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.workflow = TaskWorkflow.objects.create(
            team=self.team,
            name="Test Workflow",
        )
        self.stage1 = WorkflowStage.objects.create(
            workflow=self.workflow,
            name="Stage 1",
            key="stage1",
            position=0,
        )
        self.stage2 = WorkflowStage.objects.create(
            workflow=self.workflow,
            name="Stage 2",
            key="stage2",
            position=1,
        )

    def test_stage_creation(self):
        stage = WorkflowStage.objects.create(
            workflow=self.workflow,
            name="New Stage",
            key="new_stage",
            position=2,
            color="#ff0000",
            is_manual_only=False,
        )
        self.assertEqual(stage.workflow, self.workflow)
        self.assertEqual(stage.name, "New Stage")
        self.assertEqual(stage.key, "new_stage")
        self.assertEqual(stage.position, 2)
        self.assertEqual(stage.color, "#ff0000")
        self.assertFalse(stage.is_manual_only)
        self.assertFalse(stage.is_archived)

    def test_str_representation(self):
        self.assertEqual(str(self.stage1), "Test Workflow: Stage 1")

    def test_unique_together_constraint_key(self):
        with self.assertRaises(IntegrityError):
            WorkflowStage.objects.create(
                workflow=self.workflow,
                name="Duplicate Key",
                key="stage1",
                position=10,
            )

    def test_unique_together_constraint_position(self):
        with self.assertRaises(IntegrityError):
            WorkflowStage.objects.create(
                workflow=self.workflow,
                name="Duplicate Position",
                key="unique_key",
                position=0,
            )

    def test_next_stage_property(self):
        WorkflowStage.objects.create(
            workflow=self.workflow,
            name="Stage 3",
            key="stage3",
            position=2,
            is_archived=True,
        )
        stage4 = WorkflowStage.objects.create(
            workflow=self.workflow,
            name="Stage 4",
            key="stage4",
            position=3,
        )

        self.assertEqual(self.stage1.next_stage, self.stage2)
        self.assertEqual(self.stage2.next_stage, stage4)
        self.assertIsNone(stage4.next_stage)

    def test_archive(self):
        self.assertFalse(self.stage1.is_archived)
        self.stage1.archive()
        self.stage1.refresh_from_db()
        self.assertTrue(self.stage1.is_archived)

    def test_delete_with_fallback(self):
        task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
            workflow=self.workflow,
            current_stage=self.stage1,
        )

        self.stage1.fallback_stage = self.stage2
        self.stage1.save()
        self.stage1.delete()

        task.refresh_from_db()
        self.assertEqual(task.current_stage, self.stage2)

    def test_delete_without_fallback(self):
        task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
            workflow=self.workflow,
            current_stage=self.stage1,
        )

        self.stage1.delete()

        task.refresh_from_db()
        self.assertEqual(task.current_stage, self.stage2)

    def test_delete_last_stage(self):
        self.stage2.delete()
        task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
            workflow=self.workflow,
            current_stage=self.stage1,
        )

        self.stage1.delete()

        task.refresh_from_db()
        self.assertIsNone(task.current_stage)
        self.assertIsNone(task.workflow)

    @patch("products.tasks.backend.models.get_agent_by_id")
    def test_agent_definition_property(self, mock_get_agent):
        mock_agent = MagicMock()
        mock_get_agent.return_value = mock_agent

        self.stage1.agent_name = "test_agent"
        self.stage1.save()

        result = self.stage1.agent_definition

        mock_get_agent.assert_called_once_with("test_agent")
        self.assertEqual(result, mock_agent)

    def test_agent_definition_property_no_agent(self):
        self.stage1.agent_name = None
        self.stage1.save()

        result = self.stage1.agent_definition
        self.assertIsNone(result)


class TestTask(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.workflow = TaskWorkflow.objects.create(
            team=self.team,
            name="Test Workflow",
            is_default=True,
        )
        self.stage1 = WorkflowStage.objects.create(
            workflow=self.workflow,
            name="Backlog",
            key="backlog",
            position=0,
        )
        self.stage2 = WorkflowStage.objects.create(
            workflow=self.workflow,
            name="In Progress",
            key="in_progress",
            position=1,
        )

    @parameterized.expand(
        [
            (Task.OriginProduct.ERROR_TRACKING,),
            (Task.OriginProduct.EVAL_CLUSTERS,),
            (Task.OriginProduct.USER_CREATED,),
            (Task.OriginProduct.SUPPORT_QUEUE,),
            (Task.OriginProduct.SESSION_SUMMARIES,),
        ]
    )
    def test_task_creation_with_origin_products(self, origin_product):
        task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Test Description",
            origin_product=origin_product,
        )
        self.assertEqual(task.team, self.team)
        self.assertEqual(task.title, "Test Task")
        self.assertEqual(task.description, "Test Description")
        self.assertEqual(task.origin_product, origin_product)
        self.assertEqual(task.position, 0)

    def test_str_representation_with_workflow(self):
        task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
            workflow=self.workflow,
            current_stage=self.stage1,
        )
        self.assertEqual(str(task), "Test Task (backlog)")

    def test_str_representation_with_auto_assigned_workflow(self):
        task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        # Task gets auto-assigned to default workflow and first stage
        self.assertEqual(str(task), "Test Task (backlog)")

    def test_save_auto_assigns_first_stage(self):
        task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
            workflow=self.workflow,
        )
        self.assertEqual(task.current_stage, self.stage1)

    def test_save_clears_mismatched_stage(self):
        other_workflow = TaskWorkflow.objects.create(
            team=self.team,
            name="Other Workflow",
        )
        other_stage = WorkflowStage.objects.create(
            workflow=other_workflow,
            name="Other Stage",
            key="other",
            position=0,
        )

        task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
            workflow=self.workflow,
            current_stage=other_stage,
        )

        self.assertIsNone(task.current_stage)

    def test_repository_list_with_config(self):
        integration = Integration.objects.create(team=self.team, kind="github", config={})
        task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
            github_integration=integration,
            repository_config={
                "organization": "PostHog",
                "repository": "posthog",
            },
        )

        repo_list = task.repository_list
        self.assertEqual(len(repo_list), 1)
        self.assertEqual(repo_list[0]["org"], "PostHog")
        self.assertEqual(repo_list[0]["repo"], "posthog")
        self.assertEqual(repo_list[0]["integration_id"], integration.id)
        self.assertEqual(repo_list[0]["full_name"], "posthog/posthog")

    def test_repository_list_empty(self):
        task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        self.assertEqual(task.repository_list, [])

    @parameterized.expand(
        [
            ("PostHog", "posthog", True),
            ("PostHog", "other-repo", False),
            ("OtherOrg", "posthog", False),
        ]
    )
    def test_can_access_repository(self, org, repo, expected):
        integration = Integration.objects.create(team=self.team, kind="github", config={})
        task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
            github_integration=integration,
            repository_config={
                "organization": "PostHog",
                "repository": "posthog",
            },
        )

        self.assertEqual(task.can_access_repository(org, repo), expected)

    def test_primary_repository(self):
        integration = Integration.objects.create(team=self.team, kind="github", config={})
        task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
            github_integration=integration,
            repository_config={
                "organization": "PostHog",
                "repository": "posthog",
            },
        )

        primary_repo = task.primary_repository
        assert primary_repo is not None
        self.assertEqual(primary_repo["org"], "PostHog")
        self.assertEqual(primary_repo["repo"], "posthog")

    def test_primary_repository_none(self):
        task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        self.assertIsNone(task.primary_repository)

    def test_legacy_github_integration_from_task(self):
        integration = Integration.objects.create(team=self.team, kind="github", config={})
        task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
            github_integration=integration,
        )

        self.assertEqual(task.legacy_github_integration, integration)

    def test_legacy_github_integration_from_team(self):
        integration = Integration.objects.create(team=self.team, kind="github", config={})
        task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

        self.assertEqual(task.legacy_github_integration, integration)

    def test_effective_workflow_custom(self):
        custom_workflow = TaskWorkflow.objects.create(
            team=self.team,
            name="Custom Workflow",
        )
        task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
            workflow=custom_workflow,
        )

        self.assertEqual(task.effective_workflow, custom_workflow)

    def test_effective_workflow_default(self):
        task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

        self.assertEqual(task.effective_workflow, self.workflow)

    def test_effective_workflow_none(self):
        self.workflow.is_default = False
        self.workflow.save()

        task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

        self.assertIsNone(task.effective_workflow)

    def test_get_next_stage(self):
        task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
            workflow=self.workflow,
            current_stage=self.stage1,
        )

        self.assertEqual(task.get_next_stage(), self.stage2)

        task.current_stage = self.stage2
        task.save()

        self.assertIsNone(task.get_next_stage())

    def test_no_workflow_gets_default_workflow(self):
        task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

        # Task should be automatically assigned to the existing default workflow
        self.assertEqual(task.workflow, self.workflow)
        assert task.workflow is not None
        self.assertTrue(task.workflow.is_default)


class TestTaskSlug(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.workflow = TaskWorkflow.objects.create(
            team=self.team,
            name="Test Workflow",
            is_default=True,
        )
        WorkflowStage.objects.create(
            workflow=self.workflow,
            name="Backlog",
            key="backlog",
            position=0,
        )

    @parameterized.expand(
        [
            ("JonathanLab", "JON"),
            ("Test Team", "TES"),
            ("ABC", "ABC"),
            ("PostHog", "POS"),
            ("my team", "MYT"),
            ("123test", "123"),
            ("test", "TES"),
            ("t", "T"),
            ("", "TSK"),
        ]
    )
    def test_generate_team_prefix(self, team_name, expected_prefix):
        result = Task.generate_team_prefix(team_name)
        self.assertEqual(result, expected_prefix)

    def test_task_number_auto_generation(self):
        task = Task.objects.create(
            team=self.team,
            title="First Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        self.assertIsNotNone(task.task_number)
        self.assertEqual(task.task_number, 0)

    def test_task_number_sequential(self):
        task1 = Task.objects.create(
            team=self.team,
            title="First Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        task2 = Task.objects.create(
            team=self.team,
            title="Second Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        task3 = Task.objects.create(
            team=self.team,
            title="Third Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

        self.assertEqual(task1.task_number, 0)
        self.assertEqual(task2.task_number, 1)
        self.assertEqual(task3.task_number, 2)

    def test_slug_generation(self):
        task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        self.assertEqual(task.slug, "TES-0")

    def test_slug_with_different_teams(self):
        other_team = Team.objects.create(organization=self.organization, name="JonathanLab")
        TaskWorkflow.objects.create(
            team=other_team,
            name="Other Workflow",
            is_default=True,
        )

        task1 = Task.objects.create(
            team=self.team,
            title="Task 1",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        task2 = Task.objects.create(
            team=other_team,
            title="Task 2",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

        self.assertEqual(task1.slug, "TES-0")
        self.assertEqual(task2.slug, "JON-0")


class TestTaskProgress(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Test Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

    @parameterized.expand(
        [
            (TaskProgress.Status.STARTED,),
            (TaskProgress.Status.IN_PROGRESS,),
            (TaskProgress.Status.COMPLETED,),
            (TaskProgress.Status.FAILED,),
        ]
    )
    def test_progress_creation_with_statuses(self, status):
        progress = TaskProgress.objects.create(
            task=self.task,
            team=self.team,
            status=status,
            current_step="Test Step",
            total_steps=10,
            completed_steps=5,
        )
        self.assertEqual(progress.task, self.task)
        self.assertEqual(progress.team, self.team)
        self.assertEqual(progress.status, status)
        self.assertEqual(progress.current_step, "Test Step")
        self.assertEqual(progress.total_steps, 10)
        self.assertEqual(progress.completed_steps, 5)

    def test_str_representation(self):
        progress = TaskProgress.objects.create(
            task=self.task,
            team=self.team,
            status=TaskProgress.Status.IN_PROGRESS,
        )
        self.assertEqual(str(progress), "Progress for Test Task - In Progress")

    def test_append_output(self):
        progress = TaskProgress.objects.create(
            task=self.task,
            team=self.team,
        )

        progress.append_output("First line")
        progress.refresh_from_db()
        self.assertEqual(progress.output_log, "First line")

        progress.append_output("Second line")
        progress.refresh_from_db()
        self.assertEqual(progress.output_log, "First line\nSecond line")

    def test_update_progress(self):
        progress = TaskProgress.objects.create(
            task=self.task,
            team=self.team,
        )

        progress.update_progress(step="New Step", completed_steps=3, total_steps=10)

        progress.refresh_from_db()
        self.assertEqual(progress.current_step, "New Step")
        self.assertEqual(progress.completed_steps, 3)
        self.assertEqual(progress.total_steps, 10)

    def test_mark_completed(self):
        progress = TaskProgress.objects.create(
            task=self.task,
            team=self.team,
            status=TaskProgress.Status.IN_PROGRESS,
        )

        self.assertIsNone(progress.completed_at)
        progress.mark_completed()

        progress.refresh_from_db()
        self.assertEqual(progress.status, TaskProgress.Status.COMPLETED)
        self.assertIsNotNone(progress.completed_at)

    def test_mark_failed(self):
        progress = TaskProgress.objects.create(
            task=self.task,
            team=self.team,
            status=TaskProgress.Status.IN_PROGRESS,
        )

        error_msg = "Something went wrong"
        progress.mark_failed(error_msg)

        progress.refresh_from_db()
        self.assertEqual(progress.status, TaskProgress.Status.FAILED)
        self.assertEqual(progress.error_message, error_msg)
        self.assertIsNotNone(progress.completed_at)

    @parameterized.expand(
        [
            (0, 10, 0),
            (5, 10, 50),
            (15, 10, 100),
            (5, None, 0),
        ]
    )
    def test_progress_percentage(self, completed, total, expected):
        progress = TaskProgress.objects.create(
            task=self.task,
            team=self.team,
            completed_steps=completed,
            total_steps=total if total is not None else 0,
        )
        self.assertEqual(progress.progress_percentage, expected)

    def test_workflow_metadata(self):
        progress = TaskProgress.objects.create(
            task=self.task,
            team=self.team,
            workflow_id="workflow-123",
            workflow_run_id="run-456",
            activity_id="activity-789",
        )

        self.assertEqual(progress.workflow_id, "workflow-123")
        self.assertEqual(progress.workflow_run_id, "run-456")
        self.assertEqual(progress.activity_id, "activity-789")


class TestSandboxSnapshot(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.integration = Integration.objects.create(team=self.team, kind="github", config={})

    @parameterized.expand(
        [
            (SandboxSnapshot.Status.IN_PROGRESS,),
            (SandboxSnapshot.Status.COMPLETE,),
            (SandboxSnapshot.Status.ERROR,),
        ]
    )
    def test_snapshot_creation_with_statuses(self, status):
        external_id = f"snapshot-{uuid.uuid4()}"
        snapshot = SandboxSnapshot.objects.create(
            integration=self.integration,
            external_id=external_id,
            repos=["PostHog/posthog", "PostHog/posthog-js"],
            status=status,
        )
        self.assertEqual(snapshot.integration, self.integration)
        self.assertEqual(snapshot.external_id, external_id)
        self.assertEqual(snapshot.repos, ["PostHog/posthog", "PostHog/posthog-js"])
        self.assertEqual(snapshot.status, status)

    def test_snapshot_default_values(self):
        snapshot = SandboxSnapshot.objects.create(integration=self.integration)
        self.assertEqual(snapshot.repos, [])
        self.assertEqual(snapshot.metadata, {})
        self.assertEqual(snapshot.status, SandboxSnapshot.Status.IN_PROGRESS)

    def test_str_representation(self):
        snapshot = SandboxSnapshot.objects.create(
            integration=self.integration,
            external_id=f"snapshot-{uuid.uuid4()}",
            repos=["PostHog/posthog", "PostHog/posthog-js"],
            status=SandboxSnapshot.Status.COMPLETE,
        )
        self.assertEqual(str(snapshot), f"Snapshot {snapshot.external_id} (Complete, 2 repos)")

    def test_is_complete(self):
        snapshot = SandboxSnapshot.objects.create(
            integration=self.integration,
            status=SandboxSnapshot.Status.IN_PROGRESS,
            external_id=f"snapshot-{uuid.uuid4()}",
        )
        self.assertFalse(snapshot.is_complete())

        snapshot.status = SandboxSnapshot.Status.COMPLETE
        snapshot.save()
        self.assertTrue(snapshot.is_complete())

    @parameterized.expand(
        [
            (["PostHog/posthog", "PostHog/posthog-js"], "PostHog/posthog", True),
            (["PostHog/posthog", "PostHog/posthog-js"], "PostHog/other", False),
            ([], "PostHog/posthog", False),
        ]
    )
    def test_has_repo(self, repos, check_repo, expected):
        snapshot = SandboxSnapshot.objects.create(
            integration=self.integration, repos=repos, external_id=f"snapshot-{uuid.uuid4()}"
        )
        self.assertEqual(snapshot.has_repo(check_repo), expected)

    @parameterized.expand(
        [
            (["PostHog/posthog", "PostHog/posthog-js"], ["PostHog/posthog"], True),
            (["PostHog/posthog", "PostHog/posthog-js"], ["PostHog/posthog", "PostHog/posthog-js"], True),
            (["PostHog/posthog"], ["PostHog/posthog", "PostHog/posthog-js"], False),
            ([], ["PostHog/posthog"], False),
        ]
    )
    def test_has_repos(self, snapshot_repos, required_repos, expected):
        snapshot = SandboxSnapshot.objects.create(
            integration=self.integration, repos=snapshot_repos, external_id=f"snapshot-{uuid.uuid4()}"
        )
        self.assertEqual(snapshot.has_repos(required_repos), expected)

    def test_update_status_to_complete(self):
        snapshot = SandboxSnapshot.objects.create(integration=self.integration, external_id=f"snapshot-{uuid.uuid4()}")
        self.assertEqual(snapshot.status, SandboxSnapshot.Status.IN_PROGRESS)

        snapshot.update_status(SandboxSnapshot.Status.COMPLETE)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.status, SandboxSnapshot.Status.COMPLETE)

    def test_update_status_to_error(self):
        snapshot = SandboxSnapshot.objects.create(integration=self.integration, external_id=f"snapshot-{uuid.uuid4()}")

        snapshot.update_status(SandboxSnapshot.Status.ERROR)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.status, SandboxSnapshot.Status.ERROR)

    @parameterized.expand(
        [
            (["PostHog/posthog"], "posthog/posthog", True),
            (["PostHog/posthog"], "POSTHOG/POSTHOG", True),
            (["posthog/posthog-js"], "PostHog/PostHog-JS", True),
        ]
    )
    def test_has_repo_case_insensitive(self, repos, check_repo, expected):
        snapshot = SandboxSnapshot.objects.create(
            integration=self.integration, repos=repos, external_id=f"snapshot-{uuid.uuid4()}"
        )
        self.assertEqual(snapshot.has_repo(check_repo), expected)

    @parameterized.expand(
        [
            (["PostHog/posthog", "PostHog/posthog-js"], ["posthog/posthog"], True),
            (["PostHog/posthog", "PostHog/posthog-js"], ["POSTHOG/POSTHOG", "posthog/posthog-js"], True),
        ]
    )
    def test_has_repos_case_insensitive(self, snapshot_repos, required_repos, expected):
        snapshot = SandboxSnapshot.objects.create(
            integration=self.integration, repos=snapshot_repos, external_id=f"snapshot-{uuid.uuid4()}"
        )
        self.assertEqual(snapshot.has_repos(required_repos), expected)

    def test_get_latest_snapshot_for_integration(self):
        SandboxSnapshot.objects.create(
            integration=self.integration, status=SandboxSnapshot.Status.COMPLETE, external_id=f"snapshot-{uuid.uuid4()}"
        )
        snapshot2 = SandboxSnapshot.objects.create(
            integration=self.integration, status=SandboxSnapshot.Status.COMPLETE, external_id=f"snapshot-{uuid.uuid4()}"
        )

        latest = SandboxSnapshot.get_latest_snapshot_for_integration(self.integration.id)
        self.assertEqual(latest, snapshot2)

    def test_get_latest_snapshot_for_integration_ignores_in_progress(self):
        SandboxSnapshot.objects.create(
            integration=self.integration, status=SandboxSnapshot.Status.COMPLETE, external_id=f"snapshot-{uuid.uuid4()}"
        )
        SandboxSnapshot.objects.create(
            integration=self.integration,
            status=SandboxSnapshot.Status.IN_PROGRESS,
            external_id=f"snapshot-{uuid.uuid4()}",
        )

        latest = SandboxSnapshot.get_latest_snapshot_for_integration(self.integration.id)
        assert latest is not None
        self.assertEqual(latest.status, SandboxSnapshot.Status.COMPLETE)

    def test_get_latest_snapshot_for_integration_ignores_error(self):
        SandboxSnapshot.objects.create(
            integration=self.integration,
            status=SandboxSnapshot.Status.COMPLETE,
            external_id=f"snapshot-{uuid.uuid4()}",
        )
        SandboxSnapshot.objects.create(
            integration=self.integration,
            status=SandboxSnapshot.Status.ERROR,
            external_id=f"snapshot-{uuid.uuid4()}",
        )

        latest = SandboxSnapshot.get_latest_snapshot_for_integration(self.integration.id)
        assert latest is not None
        self.assertEqual(latest.status, SandboxSnapshot.Status.COMPLETE)

    def test_get_latest_snapshot_for_integration_none(self):
        latest = SandboxSnapshot.get_latest_snapshot_for_integration(self.integration.id)
        self.assertIsNone(latest)

    def test_get_latest_snapshot_with_repos(self):
        SandboxSnapshot.objects.create(
            integration=self.integration,
            repos=["PostHog/posthog"],
            status=SandboxSnapshot.Status.COMPLETE,
            external_id=f"snapshot-{uuid.uuid4()}",
        )
        snapshot2 = SandboxSnapshot.objects.create(
            integration=self.integration,
            repos=["PostHog/posthog", "PostHog/posthog-js"],
            status=SandboxSnapshot.Status.COMPLETE,
            external_id=f"snapshot-{uuid.uuid4()}",
        )

        result = SandboxSnapshot.get_latest_snapshot_with_repos(self.integration.id, ["PostHog/posthog"])
        self.assertEqual(result, snapshot2)

        result = SandboxSnapshot.get_latest_snapshot_with_repos(
            self.integration.id, ["PostHog/posthog", "PostHog/posthog-js"]
        )
        self.assertEqual(result, snapshot2)

    def test_get_latest_snapshot_with_repos_not_found(self):
        SandboxSnapshot.objects.create(
            integration=self.integration,
            repos=["PostHog/posthog"],
            status=SandboxSnapshot.Status.COMPLETE,
            external_id=f"snapshot-{uuid.uuid4()}",
        )

        result = SandboxSnapshot.get_latest_snapshot_with_repos(
            self.integration.id, ["PostHog/posthog", "PostHog/other"]
        )
        self.assertIsNone(result)

    def test_get_latest_snapshot_with_repos_ignores_in_progress(self):
        SandboxSnapshot.objects.create(
            integration=self.integration,
            repos=["PostHog/posthog"],
            status=SandboxSnapshot.Status.COMPLETE,
            external_id=f"snapshot-{uuid.uuid4()}",
        )
        SandboxSnapshot.objects.create(
            integration=self.integration,
            repos=["PostHog/posthog", "PostHog/posthog-js"],
            status=SandboxSnapshot.Status.IN_PROGRESS,
            external_id=f"snapshot-{uuid.uuid4()}",
        )

        result = SandboxSnapshot.get_latest_snapshot_with_repos(
            self.integration.id, ["PostHog/posthog", "PostHog/posthog-js"]
        )
        self.assertIsNone(result)

    def test_multiple_snapshots_per_integration(self):
        snapshot1 = SandboxSnapshot.objects.create(integration=self.integration, external_id=f"snapshot-{uuid.uuid4()}")
        snapshot2 = SandboxSnapshot.objects.create(integration=self.integration, external_id=f"snapshot-{uuid.uuid4()}")
        snapshot3 = SandboxSnapshot.objects.create(integration=self.integration, external_id=f"snapshot-{uuid.uuid4()}")

        snapshots = SandboxSnapshot.objects.filter(integration=self.integration)
        self.assertEqual(snapshots.count(), 3)
        self.assertIn(snapshot1, snapshots)
        self.assertIn(snapshot2, snapshots)
        self.assertIn(snapshot3, snapshots)

    def test_set_null_on_integration_delete(self):
        SandboxSnapshot.objects.create(integration=self.integration, external_id=f"snapshot-{uuid.uuid4()}")
        SandboxSnapshot.objects.create(integration=self.integration, external_id=f"snapshot-{uuid.uuid4()}")

        self.assertEqual(SandboxSnapshot.objects.filter(integration=self.integration).count(), 2)

        self.integration.delete()

        self.assertEqual(SandboxSnapshot.objects.filter(integration__isnull=True).count(), 2)
