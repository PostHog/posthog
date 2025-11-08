import json
import uuid

from unittest.mock import patch

from django.conf import settings
from django.test import TestCase

from parameterized import parameterized

from posthog.models import Integration, Organization, Team
from posthog.models.user import User
from posthog.storage import object_storage

from products.tasks.backend.models import SandboxSnapshot, Task, TaskRun


class TestTask(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")

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

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_and_run_minimal(self, mock_execute_workflow):
        user = User.objects.create(email="test@test.com")
        Integration.objects.create(team=self.team, kind="github", config={})

        task = Task.create_and_run(
            team=self.team,
            title="Test Create and Run",
            description="Test Description",
            origin_product=Task.OriginProduct.USER_CREATED,
            user_id=user.id,
            repository="posthog/posthog",
        )

        self.assertIsNotNone(task.id)
        self.assertEqual(task.title, "Test Create and Run")
        self.assertEqual(task.description, "Test Description")
        self.assertEqual(task.origin_product, Task.OriginProduct.USER_CREATED)
        self.assertEqual(task.team, self.team)
        self.assertEqual(task.created_by, user)
        self.assertEqual(task.repository_config, {"organization": "posthog", "repository": "posthog"})

        mock_execute_workflow.assert_called_once_with(
            task_id=str(task.id),
            team_id=self.team.id,
            user_id=user.id,
        )

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_and_run_with_repository(self, mock_execute_workflow):
        user = User.objects.create(email="test@test.com")
        Integration.objects.create(team=self.team, kind="github", config={})

        task = Task.create_and_run(
            team=self.team,
            title="Test Task",
            description="Test Description",
            origin_product=Task.OriginProduct.USER_CREATED,
            user_id=user.id,
            repository="posthog/posthog-js",
        )

        self.assertEqual(task.repository_config["organization"], "posthog")
        self.assertEqual(task.repository_config["repository"], "posthog-js")

        mock_execute_workflow.assert_called_once()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_and_run_invalid_repository_format(self, mock_execute_workflow):
        user = User.objects.create(email="test@test.com")
        Integration.objects.create(team=self.team, kind="github", config={})

        with self.assertRaises(ValueError) as cm:
            Task.create_and_run(
                team=self.team,
                title="Test Task",
                description="Test Description",
                origin_product=Task.OriginProduct.USER_CREATED,
                user_id=user.id,
                repository="invalid-format",
            )

        self.assertIn("Repository must be in format 'organization/repository'", str(cm.exception))
        mock_execute_workflow.assert_not_called()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_and_run_with_github_integration(self, mock_execute_workflow):
        user = User.objects.create(email="test@test.com")
        integration = Integration.objects.create(team=self.team, kind="github", config={})

        task = Task.create_and_run(
            team=self.team,
            title="Test Task",
            description="Test Description",
            origin_product=Task.OriginProduct.USER_CREATED,
            user_id=user.id,
            repository="posthog/posthog",
        )

        self.assertEqual(task.github_integration, integration)
        mock_execute_workflow.assert_called_once()


class TestTaskSlug(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")

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


class TestTaskRun(TestCase):
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
            (TaskRun.Status.STARTED,),
            (TaskRun.Status.IN_PROGRESS,),
            (TaskRun.Status.COMPLETED,),
            (TaskRun.Status.FAILED,),
        ]
    )
    def test_run_creation_with_statuses(self, status):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=status,
        )
        self.assertEqual(run.task, self.task)
        self.assertEqual(run.team, self.team)
        self.assertEqual(run.status, status)

    def test_str_representation(self):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
        )
        self.assertEqual(str(run), "Run for Test Task - In Progress")

    def test_append_log_to_empty(self):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
        )

        entries = [{"type": "info", "message": "First log entry"}]
        run.append_log(entries)
        run.refresh_from_db()

        self.assertIsNotNone(run.log_storage_path)
        self.assertTrue(run.has_s3_logs)
        log_content = object_storage.read(run.log_storage_path)
        self.assertIsNotNone(log_content)

        log_entries = [json.loads(line) for line in log_content.strip().split("\n")]
        self.assertEqual(len(log_entries), 1)
        self.assertEqual(log_entries[0]["type"], "info")
        self.assertEqual(log_entries[0]["message"], "First log entry")

    def test_append_log_multiple_entries(self):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
        )

        entries = [
            {"type": "info", "message": "First entry"},
            {"type": "warning", "message": "Second entry"},
            {"type": "error", "message": "Third entry"},
        ]
        run.append_log(entries)
        run.refresh_from_db()

        self.assertIsNotNone(run.log_storage_path)
        self.assertTrue(run.has_s3_logs)

        log_content = object_storage.read(run.log_storage_path)
        self.assertIsNotNone(log_content)

        log_entries = [json.loads(line) for line in log_content.strip().split("\n")]
        self.assertEqual(len(log_entries), 3)
        self.assertEqual(log_entries[0]["type"], "info")
        self.assertEqual(log_entries[1]["type"], "warning")
        self.assertEqual(log_entries[2]["type"], "error")

    def test_append_log_to_existing(self):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
        )

        first_entries = [{"type": "info", "message": "First entry"}]
        run.append_log(first_entries)

        new_entries = [
            {"type": "success", "message": "New entry 1"},
            {"type": "debug", "message": "New entry 2"},
        ]
        run.append_log(new_entries)
        run.refresh_from_db()

        self.assertIsNotNone(run.log_storage_path)
        self.assertTrue(run.has_s3_logs)

        log_content = object_storage.read(run.log_storage_path)
        self.assertIsNotNone(log_content)

        log_entries = [json.loads(line) for line in log_content.strip().split("\n")]
        self.assertEqual(len(log_entries), 3)
        self.assertEqual(log_entries[0]["message"], "First entry")
        self.assertEqual(log_entries[1]["message"], "New entry 1")
        self.assertEqual(log_entries[2]["message"], "New entry 2")

    def test_log_file_tagged_with_ttl(self):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
        )

        entries = [{"type": "info", "message": "Test entry"}]
        run.append_log(entries)
        run.refresh_from_db()

        self.assertIsNotNone(run.log_storage_path)

        # Verify S3 object has TTL tags
        from botocore.exceptions import ClientError

        from posthog.storage.object_storage import object_storage_client

        try:
            client = object_storage_client()
            response = client.aws_client.get_object_tagging(
                Bucket=settings.OBJECT_STORAGE_BUCKET, Key=run.log_storage_path
            )
            tags = {tag["Key"]: tag["Value"] for tag in response.get("TagSet", [])}
            self.assertEqual(tags.get("ttl_days"), "30")
            self.assertEqual(tags.get("team_id"), str(self.team.id))
        except (ClientError, AttributeError):
            # Tagging might not be available in test environment
            pass

    def test_mark_completed(self):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
        )

        self.assertIsNone(run.completed_at)
        run.mark_completed()

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.COMPLETED)
        self.assertIsNotNone(run.completed_at)

    def test_mark_failed(self):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
        )

        error_msg = "Something went wrong"
        run.mark_failed(error_msg)

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.FAILED)
        self.assertEqual(run.error_message, error_msg)
        self.assertIsNotNone(run.completed_at)

    def test_output_jsonfield(self):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            output={"pr_url": "https://github.com/org/repo/pull/123", "commit_sha": "abc123"},
        )

        run.refresh_from_db()
        assert run.output is not None
        self.assertEqual(run.output["pr_url"], "https://github.com/org/repo/pull/123")
        self.assertEqual(run.output["commit_sha"], "abc123")

        run.output["status"] = "success"
        run.save()
        run.refresh_from_db()
        assert run.output is not None
        self.assertEqual(run.output["status"], "success")

    def test_state_jsonfield(self):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            state={"last_checkpoint": "step_3", "variables": {"x": 1, "y": 2}},
        )

        run.refresh_from_db()
        self.assertEqual(run.state["last_checkpoint"], "step_3")
        self.assertEqual(run.state["variables"]["x"], 1)

        run.state["completed_checkpoints"] = ["step_1", "step_2", "step_3"]
        run.save()
        run.refresh_from_db()
        self.assertEqual(len(run.state["completed_checkpoints"]), 3)


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

    def test_delete_without_external_id_succeeds(self):
        snapshot = SandboxSnapshot.objects.create(integration=self.integration)

        snapshot.delete()

        self.assertEqual(SandboxSnapshot.objects.filter(id=snapshot.id).count(), 0)
