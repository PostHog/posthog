import json
import uuid
import secrets
from typing import ClassVar

from unittest.mock import AsyncMock, patch

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from parameterized import parameterized

from posthog.models import Integration, Organization, Team
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration
from posthog.storage import object_storage

from products.tasks.backend.models import CodeInvite, SandboxEnvironment, SandboxSnapshot, Task, TaskRun


class TestTask(TestCase):
    organization: ClassVar[Organization]
    team: ClassVar[Team]

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Test Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Test Team")

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
        assert task.team == self.team
        assert task.title == "Test Task"
        assert task.description == "Test Description"
        assert task.origin_product == origin_product

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

        assert task.id is not None
        assert task.title == "Test Create and Run"
        assert task.description == "Test Description"
        assert task.origin_product == Task.OriginProduct.USER_CREATED
        assert task.team == self.team
        assert task.created_by == user
        assert task.repository == "posthog/posthog"

        mock_execute_workflow.assert_called_once()
        call_args = mock_execute_workflow.call_args
        assert call_args.kwargs["task_id"] == str(task.id)
        assert call_args.kwargs["team_id"] == self.team.id
        assert call_args.kwargs["user_id"] == user.id
        assert call_args.kwargs["run_id"] is not None
        task_run = TaskRun.objects.get(id=call_args.kwargs["run_id"])
        assert task_run.task == task
        assert task_run.status == TaskRun.Status.QUEUED

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_and_run_threads_initial_permission_mode_into_state(self, mock_execute_workflow):
        user = User.objects.create(email="test@test.com")
        Integration.objects.create(team=self.team, kind="github", config={})

        task = Task.create_and_run(
            team=self.team,
            title="Slack Task",
            description="Slack Description",
            origin_product=Task.OriginProduct.SLACK,
            user_id=user.id,
            repository="posthog/posthog",
            initial_permission_mode="bypassPermissions",
        )

        run_id = mock_execute_workflow.call_args.kwargs["run_id"]
        task_run = TaskRun.objects.get(id=run_id)
        assert task_run.state["initial_permission_mode"] == "bypassPermissions"
        assert task.origin_product == Task.OriginProduct.SLACK

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_and_run_omits_permission_mode_when_not_provided(self, mock_execute_workflow):
        user = User.objects.create(email="test@test.com")
        Integration.objects.create(team=self.team, kind="github", config={})

        Task.create_and_run(
            team=self.team,
            title="Plain Task",
            description="Plain Description",
            origin_product=Task.OriginProduct.USER_CREATED,
            user_id=user.id,
            repository="posthog/posthog",
        )

        run_id = mock_execute_workflow.call_args.kwargs["run_id"]
        task_run = TaskRun.objects.get(id=run_id)
        assert "initial_permission_mode" not in task_run.state

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

        assert task.repository == "posthog/posthog-js"

        mock_execute_workflow.assert_called_once()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_and_run_invalid_repository_format(self, mock_execute_workflow):
        user = User.objects.create(email="test@test.com")
        Integration.objects.create(team=self.team, kind="github", config={})

        with self.assertRaises(ValidationError) as cm:
            Task.create_and_run(
                team=self.team,
                title="Test Task",
                description="Test Description",
                origin_product=Task.OriginProduct.USER_CREATED,
                user_id=user.id,
                repository="invalid-format",
            )

        assert "Format for repository is organization/repo" in str(cm.exception)
        mock_execute_workflow.assert_not_called()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_and_run_public_repo_without_integration(self, mock_execute_workflow):
        user = User.objects.create(email="test@test.com")

        task = Task.create_and_run(
            team=self.team,
            title="Test Task",
            description="Test Description",
            origin_product=Task.OriginProduct.USER_CREATED,
            user_id=user.id,
            repository="posthog/hedgebox",
        )

        assert task.repository == "posthog/hedgebox"
        assert task.github_integration is None
        mock_execute_workflow.assert_called_once()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_and_run_non_public_repo_without_integration_raises(self, mock_execute_workflow):
        user = User.objects.create(email="test@test.com")

        with self.assertRaises(ValueError) as cm:
            Task.create_and_run(
                team=self.team,
                title="Test Task",
                description="Test Description",
                origin_product=Task.OriginProduct.USER_CREATED,
                user_id=user.id,
                repository="posthog/posthog",
            )

        assert "does not have a GitHub integration" in str(cm.exception)
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

        assert task.github_integration == integration
        mock_execute_workflow.assert_called_once()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_and_run_signal_report_falls_back_to_user_integration(self, mock_execute_workflow):
        # Signal reports are BOT-authored. When the team has no Integration row but the task
        # creator has a UserIntegration that grants access to the repo, we should accept it
        # instead of raising "Team does not have a GitHub integration".
        user = User.objects.create(email="signal-report@test.com")
        OrganizationMembership.objects.create(user=user, organization=self.organization)
        user_integration = UserIntegration.objects.create(
            user=user,
            kind=UserIntegration.IntegrationKind.GITHUB,
            integration_id="install-1",
            config={"installation_id": "install-1"},
            sensitive_config={"access_token": "ghs_user_install"},
            repository_cache=[{"full_name": "posthog/posthog", "id": 1}],
        )

        task = Task.create_and_run(
            team=self.team,
            title="Signal Report",
            description="Research",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
            user_id=user.id,
            repository="posthog/posthog",
        )

        assert task.github_integration is None
        assert task.github_user_integration == user_integration
        mock_execute_workflow.assert_called_once()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_and_run_signal_report_raises_when_no_integration_anywhere(self, mock_execute_workflow):
        user = User.objects.create(email="signal-no-int@test.com")
        OrganizationMembership.objects.create(user=user, organization=self.organization)

        with self.assertRaises(ValueError) as cm:
            Task.create_and_run(
                team=self.team,
                title="Signal Report",
                description="Research",
                origin_product=Task.OriginProduct.SIGNAL_REPORT,
                user_id=user.id,
                repository="posthog/posthog",
            )

        assert "does not have a GitHub integration" in str(cm.exception)
        mock_execute_workflow.assert_not_called()

    @parameterized.expand(
        [
            ("posthog-repo",),
            ("noslashhere",),
        ]
    )
    def test_repository_validation_fails_without_slash(self, repository):
        with self.assertRaises(ValidationError) as cm:
            Task.objects.create(
                team=self.team,
                title="Test Task",
                description="Description",
                origin_product=Task.OriginProduct.USER_CREATED,
                repository=repository,
            )

        assert "Format for repository is organization/repo" in str(cm.exception)

    @parameterized.expand(
        [
            ("PostHog/posthog", "posthog/posthog"),
            ("posthog/PostHog-JS", "posthog/posthog-js"),
            ("PostHog/PostHog", "posthog/posthog"),
            ("POSTHOG/POSTHOG-JS", "posthog/posthog-js"),
            ("posthog/posthog-js", "posthog/posthog-js"),
        ]
    )
    def test_repository_converts_to_lowercase(self, input_repo, expected_repo):
        task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
            repository=input_repo,
        )

        assert task.repository == expected_repo

    def test_soft_delete(self):
        task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

        assert not task.deleted
        assert task.deleted_at is None

        task.soft_delete()

        task = Task.objects.get(pk=task.pk)
        assert task.deleted
        assert task.deleted_at is not None

    def test_hard_delete_blocked(self):
        task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

        with self.assertRaises(Exception) as cm:
            task.delete()

        assert "Cannot hard delete Task" in str(cm.exception)
        assert "Use soft_delete() instead" in str(cm.exception)

        task.refresh_from_db()
        assert task.id is not None

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_and_run_internal_defaults_to_false(self, mock_execute_workflow):
        user = User.objects.create(email="internal_default@test.com")
        Integration.objects.create(team=self.team, kind="github", config={})

        task = Task.create_and_run(
            team=self.team,
            title="Non-internal Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
            user_id=user.id,
            repository="posthog/posthog",
        )

        assert not task.internal

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_and_run_with_internal_true(self, mock_execute_workflow):
        user = User.objects.create(email="internal_true@test.com")
        Integration.objects.create(team=self.team, kind="github", config={})

        task = Task.create_and_run(
            team=self.team,
            title="Internal Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
            user_id=user.id,
            repository="posthog/posthog",
            internal=True,
        )

        task.refresh_from_db()
        assert task.internal


class TestTaskSlug(TestCase):
    organization: ClassVar[Organization]
    team: ClassVar[Team]

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Test Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Test Team")

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
        assert result == expected_prefix

    def test_task_number_auto_generation(self):
        task = Task.objects.create(
            team=self.team,
            title="First Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        assert task.task_number is not None
        assert task.task_number == 0

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

        assert task1.task_number == 0
        assert task2.task_number == 1
        assert task3.task_number == 2

    def test_slug_generation(self):
        task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        assert task.slug == "TES-0"

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

        assert task1.slug == "TES-0"
        assert task2.slug == "JON-0"


class TestTaskRun(TestCase):
    organization: ClassVar[Organization]
    team: ClassVar[Team]
    task: ClassVar[Task]

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Test Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Test Team")
        cls.task = Task.objects.create(
            team=cls.team,
            title="Test Task",
            description="Test Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

    @parameterized.expand(
        [
            (TaskRun.Status.QUEUED,),
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
        assert run.task == self.task
        assert run.team == self.team
        assert run.status == status

    def test_str_representation(self):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
        )
        assert str(run) == "Run for Test Task - In Progress"

    @patch("products.tasks.backend.models.publish_task_run_stream_event")
    def test_create_run_seeds_stream_state_event(self, mock_publish_stream_event):
        run = self.task.create_run(branch="main")

        mock_publish_stream_event.assert_called_once()
        call_args = mock_publish_stream_event.call_args
        assert call_args.args[0] == str(run.id)
        assert call_args.args[1]["type"] == "task_run_state"
        assert call_args.args[1]["status"] == TaskRun.Status.QUEUED
        assert call_args.args[1]["branch"] == "main"

    def test_create_run_does_not_inject_permission_mode_by_default(self):
        run = self.task.create_run(mode="interactive")

        assert "initial_permission_mode" not in run.state

    def test_s3_prefixes_keep_existing_logs_and_artifact_paths(self):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
        )

        assert run.log_url == f"tasks/logs/team_{self.team.id}/task_{self.task.id}/run_{run.id}.jsonl"
        assert run.get_artifact_s3_prefix() == f"tasks/artifacts/team_{self.team.id}/task_{self.task.id}/run_{run.id}"

    def test_update_state_atomic_merges_against_latest_state(self):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            state={
                "mode": "interactive",
                "pending_user_message": "read the attachment",
                "pending_user_artifact_ids": ["artifact-123"],
            },
        )

        TaskRun.update_state_atomic(
            run.id,
            remove_keys=["pending_user_message", "pending_user_artifact_ids"],
        )
        TaskRun.update_state_atomic(
            run.id,
            updates={
                "sandbox_id": "sandbox-123",
                "sandbox_url": "https://sandbox.example.com",
            },
        )

        run.refresh_from_db()
        assert run.state["mode"] == "interactive"
        assert run.state["sandbox_id"] == "sandbox-123"
        assert run.state["sandbox_url"] == "https://sandbox.example.com"
        assert "pending_user_message" not in run.state
        assert "pending_user_artifact_ids" not in run.state

    def test_mutate_state_atomic_can_derive_values_under_lock(self):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            state={"slack_sent_relay_ids": ["relay-1"]},
        )

        def append_relay(state: dict[str, list[str]]) -> None:
            sent_relay_ids = state.get("slack_sent_relay_ids") or []
            sent_relay_ids.append("relay-2")
            state["slack_sent_relay_ids"] = sent_relay_ids

        TaskRun.mutate_state_atomic(run.id, append_relay)

        run.refresh_from_db()
        assert run.state["slack_sent_relay_ids"] == ["relay-1", "relay-2"]

    def test_append_log_to_empty(self):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
        )

        entries = [{"type": "info", "message": "First log entry"}]
        run.append_log(entries)
        run.refresh_from_db()

        assert run.log_url is not None
        log_content = object_storage.read(run.log_url)
        assert log_content is not None

        log_entries = [json.loads(line) for line in log_content.strip().split("\n")]
        assert len(log_entries) == 1
        assert log_entries[0]["type"] == "info"
        assert log_entries[0]["message"] == "First log entry"

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

        assert run.log_url is not None
        log_content = object_storage.read(run.log_url)
        assert log_content is not None

        log_entries = [json.loads(line) for line in log_content.strip().split("\n")]
        assert len(log_entries) == 3
        assert log_entries[0]["type"] == "info"
        assert log_entries[1]["type"] == "warning"
        assert log_entries[2]["type"] == "error"

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

        assert run.log_url is not None
        log_content = object_storage.read(run.log_url)
        assert log_content is not None

        log_entries = [json.loads(line) for line in log_content.strip().split("\n")]
        assert len(log_entries) == 3
        assert log_entries[0]["message"] == "First entry"
        assert log_entries[1]["message"] == "New entry 1"
        assert log_entries[2]["message"] == "New entry 2"

    def test_log_file_tagged_with_ttl(self):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
        )

        entries = [{"type": "info", "message": "Test entry"}]
        run.append_log(entries)
        run.refresh_from_db()

        assert run.log_url is not None

        # Verify S3 object has TTL tags
        from botocore.exceptions import ClientError

        from posthog.storage.object_storage import ObjectStorage, object_storage_client

        try:
            client = object_storage_client()
            if isinstance(client, ObjectStorage):
                response = client.aws_client.get_object_tagging(Bucket=settings.OBJECT_STORAGE_BUCKET, Key=run.log_url)
                tags = {tag["Key"]: tag["Value"] for tag in response.get("TagSet", [])}
                assert tags.get("ttl_days") == "30"
                assert tags.get("team_id") == str(self.team.id)
        except (ClientError, AttributeError):
            # Tagging might not be available in test environment
            pass

    def test_mark_completed(self):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
        )

        assert run.completed_at is None
        run.mark_completed()

        run.refresh_from_db()
        assert run.status == TaskRun.Status.COMPLETED
        assert run.completed_at is not None

    def test_mark_failed(self):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
        )

        error_msg = "Something went wrong"
        run.mark_failed(error_msg)

        run.refresh_from_db()
        assert run.status == TaskRun.Status.FAILED
        assert run.error_message == error_msg
        assert run.completed_at is not None

    def test_output_jsonfield(self):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            output={"pr_url": "https://github.com/org/repo/pull/123", "commit_sha": "abc123"},
        )

        run.refresh_from_db()
        assert run.output is not None
        assert run.output["pr_url"] == "https://github.com/org/repo/pull/123"
        assert run.output["commit_sha"] == "abc123"

        run.output["status"] = "success"
        run.save()
        run.refresh_from_db()
        assert run.output is not None
        assert run.output["status"] == "success"

    def test_state_jsonfield(self):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            state={"last_checkpoint": "step_3", "variables": {"x": 1, "y": 2}},
        )

        run.refresh_from_db()
        assert run.state["last_checkpoint"] == "step_3"
        assert run.state["variables"]["x"] == 1

        run.state["completed_checkpoints"] = ["step_1", "step_2", "step_3"]
        run.save()
        run.refresh_from_db()
        assert len(run.state["completed_checkpoints"]) == 3

    def test_delete_blocked(self):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
        )

        with self.assertRaises(Exception) as cm:
            run.delete()

        assert "Cannot delete TaskRun" in str(cm.exception)
        assert "immutable" in str(cm.exception)

        run.refresh_from_db()
        assert run.id is not None

    def test_emit_console_event_acp_format(self):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
        )

        run.emit_console_event("info", "Test message")

        log_content = object_storage.read(run.log_url)
        assert log_content is not None
        entry = json.loads(log_content.strip())

        assert entry["type"] == "notification"
        assert "timestamp" in entry
        assert entry["notification"]["jsonrpc"] == "2.0"
        assert entry["notification"]["method"] == "_posthog/console"
        assert entry["notification"]["params"]["sessionId"] == str(run.id)
        assert entry["notification"]["params"]["level"] == "info"
        assert entry["notification"]["params"]["message"] == "Test message"

    @patch("products.tasks.backend.models.publish_task_run_stream_event")
    def test_emit_console_event_publishes_to_stream(self, mock_publish_stream_event):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
        )

        run.emit_console_event("info", "Test message")

        mock_publish_stream_event.assert_called_once()
        call_args = mock_publish_stream_event.call_args
        assert call_args.args[0] == str(run.id)
        assert call_args.args[1]["notification"]["method"] == "_posthog/console"

    def test_emit_progress_event_acp_format(self):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
        )

        run.emit_progress_event(
            "container",
            "in_progress",
            "Setting up cloud container",
            group="setup",
            detail="provisioning",
        )

        log_content = object_storage.read(run.log_url)
        assert log_content is not None
        entry = json.loads(log_content.strip())

        assert entry["type"] == "notification"
        assert "timestamp" in entry
        assert entry["notification"]["jsonrpc"] == "2.0"
        assert entry["notification"]["method"] == "_posthog/progress"
        params = entry["notification"]["params"]
        assert params["sessionId"] == str(run.id)
        assert params["step"] == "container"
        assert params["status"] == "in_progress"
        assert params["label"] == "Setting up cloud container"
        assert params["group"] == "setup"
        assert params["detail"] == "provisioning"

    def test_emit_progress_event_omits_detail_when_not_provided(self):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
        )

        run.emit_progress_event("agent", "completed", "Started agent", group="setup")

        log_content = object_storage.read(run.log_url)
        assert log_content is not None
        entry = json.loads(log_content.strip())

        params = entry["notification"]["params"]
        assert "detail" not in params
        assert params["group"] == "setup"

    @patch("products.tasks.backend.models.publish_task_run_stream_event")
    def test_emit_progress_event_publishes_to_stream(self, mock_publish_stream_event):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
        )

        run.emit_progress_event("clone", "completed", "Cloned repository", group="setup")

        mock_publish_stream_event.assert_called_once()
        call_args = mock_publish_stream_event.call_args
        assert call_args.args[0] == str(run.id)
        assert call_args.args[1]["notification"]["method"] == "_posthog/progress"
        assert call_args.args[1]["notification"]["params"]["step"] == "clone"
        assert call_args.args[1]["notification"]["params"]["group"] == "setup"

    @parameterized.expand(
        [
            (0, "stdout output", "stderr output"),
            (1, "failed stdout", "error message"),
            (137, "", "killed by signal"),
        ]
    )
    def test_emit_sandbox_output_acp_format(self, exit_code, stdout, stderr):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
        )

        run.emit_sandbox_output(stdout, stderr, exit_code)

        log_content = object_storage.read(run.log_url)
        assert log_content is not None
        entry = json.loads(log_content.strip())

        assert entry["type"] == "notification"
        assert "timestamp" in entry
        assert entry["notification"]["jsonrpc"] == "2.0"
        assert entry["notification"]["method"] == "_posthog/sandbox_output"
        assert entry["notification"]["params"]["sessionId"] == str(run.id)
        assert entry["notification"]["params"]["stdout"] == stdout
        assert entry["notification"]["params"]["stderr"] == stderr
        assert entry["notification"]["params"]["exitCode"] == exit_code

    @patch("products.tasks.backend.models.publish_task_run_stream_event")
    def test_emit_sandbox_output_publishes_to_stream(self, mock_publish_stream_event):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
        )

        run.emit_sandbox_output("stdout output", "stderr output", 0)

        mock_publish_stream_event.assert_called_once()
        call_args = mock_publish_stream_event.call_args
        assert call_args.args[0] == str(run.id)
        assert call_args.args[1]["notification"]["method"] == "_posthog/sandbox_output"

    @parameterized.expand(
        [
            ("background_mode", {"mode": "background"}, True),
            ("default_mode_is_background", {}, True),
            ("interactive_mode", {"mode": "interactive"}, True),
        ]
    )
    @patch("posthog.temporal.common.client.sync_connect")
    def test_heartbeat_workflow_mode_filtering(self, _name, state, expect_signal, mock_connect):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            state=state,
        )

        from django.core.cache import cache

        cache.delete(f"tasks:task_run:heartbeat:{run.id}:active")

        run.heartbeat_workflow(agent_active=True)

        if expect_signal:
            mock_connect.assert_called_once()
        else:
            mock_connect.assert_not_called()

        cache.delete(f"tasks:task_run:heartbeat:{run.id}:active")

    @patch("posthog.temporal.common.client.sync_connect")
    def test_heartbeat_workflow_rate_limited_by_cache(self, mock_connect):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            state={"mode": "background"},
        )

        from django.core.cache import cache

        cache_key = f"tasks:task_run:heartbeat:{run.id}:active"
        cache.delete(cache_key)
        handle = mock_connect.return_value.get_workflow_handle.return_value
        handle.signal = AsyncMock()

        run.heartbeat_workflow(agent_active=True)
        mock_connect.assert_called_once()
        handle.signal.assert_called_once()
        assert handle.signal.call_args.kwargs == {"arg": True}

        mock_connect.reset_mock()
        run.heartbeat_workflow(agent_active=True)
        mock_connect.assert_not_called()

        cache.delete(cache_key)

    @patch("posthog.temporal.common.client.sync_connect")
    def test_heartbeat_workflow_ignores_idle_heartbeats(self, mock_connect):
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            state={"mode": "background"},
        )

        from django.core.cache import cache

        cache.delete(f"tasks:task_run:heartbeat:{run.id}:active")

        handle = mock_connect.return_value.get_workflow_handle.return_value
        handle.signal = AsyncMock()

        run.heartbeat_workflow(agent_active=False)
        mock_connect.assert_not_called()

        run.heartbeat_workflow(agent_active=True)

        mock_connect.assert_called_once()
        handle.signal.assert_called_once()
        assert handle.signal.call_args.kwargs == {"arg": True}

        cache.delete(f"tasks:task_run:heartbeat:{run.id}:active")


class TestSandboxSnapshot(TestCase):
    organization: ClassVar[Organization]
    team: ClassVar[Team]
    integration: ClassVar[Integration]

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Test Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Test Team")
        cls.integration = Integration.objects.create(team=cls.team, kind="github", config={})

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
        assert snapshot.integration == self.integration
        assert snapshot.external_id == external_id
        assert snapshot.repos == ["PostHog/posthog", "PostHog/posthog-js"]
        assert snapshot.status == status

    def test_snapshot_default_values(self):
        snapshot = SandboxSnapshot.objects.create(integration=self.integration)
        assert snapshot.repos == []
        assert snapshot.metadata == {}
        assert snapshot.status == SandboxSnapshot.Status.IN_PROGRESS

    def test_str_representation(self):
        snapshot = SandboxSnapshot.objects.create(
            integration=self.integration,
            external_id=f"snapshot-{uuid.uuid4()}",
            repos=["PostHog/posthog", "PostHog/posthog-js"],
            status=SandboxSnapshot.Status.COMPLETE,
        )
        assert str(snapshot) == f"Snapshot {snapshot.external_id} (Complete, 2 repos)"

    def test_is_complete(self):
        snapshot = SandboxSnapshot.objects.create(
            integration=self.integration,
            status=SandboxSnapshot.Status.IN_PROGRESS,
            external_id=f"snapshot-{uuid.uuid4()}",
        )
        assert not snapshot.is_complete()

        snapshot.status = SandboxSnapshot.Status.COMPLETE
        snapshot.save()
        assert snapshot.is_complete()

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
        assert snapshot.has_repo(check_repo) == expected

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
        assert snapshot.has_repos(required_repos) == expected

    def test_update_status_to_complete(self):
        snapshot = SandboxSnapshot.objects.create(integration=self.integration, external_id=f"snapshot-{uuid.uuid4()}")
        assert snapshot.status == SandboxSnapshot.Status.IN_PROGRESS

        snapshot.update_status(SandboxSnapshot.Status.COMPLETE)
        snapshot.refresh_from_db()
        assert snapshot.status == SandboxSnapshot.Status.COMPLETE

    def test_update_status_to_error(self):
        snapshot = SandboxSnapshot.objects.create(integration=self.integration, external_id=f"snapshot-{uuid.uuid4()}")

        snapshot.update_status(SandboxSnapshot.Status.ERROR)
        snapshot.refresh_from_db()
        assert snapshot.status == SandboxSnapshot.Status.ERROR

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
        assert snapshot.has_repo(check_repo) == expected

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
        assert snapshot.has_repos(required_repos) == expected

    def test_get_latest_snapshot_for_integration(self):
        SandboxSnapshot.objects.create(
            integration=self.integration, status=SandboxSnapshot.Status.COMPLETE, external_id=f"snapshot-{uuid.uuid4()}"
        )
        snapshot2 = SandboxSnapshot.objects.create(
            integration=self.integration, status=SandboxSnapshot.Status.COMPLETE, external_id=f"snapshot-{uuid.uuid4()}"
        )

        latest = SandboxSnapshot.get_latest_snapshot_for_integration(self.integration.id)
        assert latest == snapshot2

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
        assert latest.status == SandboxSnapshot.Status.COMPLETE

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
        assert latest.status == SandboxSnapshot.Status.COMPLETE

    def test_get_latest_snapshot_for_integration_none(self):
        latest = SandboxSnapshot.get_latest_snapshot_for_integration(self.integration.id)
        assert latest is None

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
        assert result == snapshot2

        result = SandboxSnapshot.get_latest_snapshot_with_repos(
            self.integration.id, ["PostHog/posthog", "PostHog/posthog-js"]
        )
        assert result == snapshot2

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
        assert result is None

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
        assert result is None

    def test_multiple_snapshots_per_integration(self):
        snapshot1 = SandboxSnapshot.objects.create(integration=self.integration, external_id=f"snapshot-{uuid.uuid4()}")
        snapshot2 = SandboxSnapshot.objects.create(integration=self.integration, external_id=f"snapshot-{uuid.uuid4()}")
        snapshot3 = SandboxSnapshot.objects.create(integration=self.integration, external_id=f"snapshot-{uuid.uuid4()}")

        snapshots = SandboxSnapshot.objects.filter(integration=self.integration)
        assert snapshots.count() == 3
        assert snapshot1 in snapshots
        assert snapshot2 in snapshots
        assert snapshot3 in snapshots

    def test_set_null_on_integration_delete(self):
        SandboxSnapshot.objects.create(integration=self.integration, external_id=f"snapshot-{uuid.uuid4()}")
        SandboxSnapshot.objects.create(integration=self.integration, external_id=f"snapshot-{uuid.uuid4()}")

        assert SandboxSnapshot.objects.filter(integration=self.integration).count() == 2

        self.integration.delete()

        assert SandboxSnapshot.objects.filter(integration__isnull=True).count() == 2

    def test_delete_without_external_id_succeeds(self):
        snapshot = SandboxSnapshot.objects.create(integration=self.integration)

        snapshot.delete()

        assert SandboxSnapshot.objects.filter(id=snapshot.id).count() == 0


class TestSandboxEnvironment(TestCase):
    organization: ClassVar[Organization]
    team: ClassVar[Team]
    user: ClassVar[User]

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Test Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Test Team")
        cls.user = User.objects.create(email="test@posthog.com")

    def test_default_values(self):
        env = SandboxEnvironment.objects.create(
            team=self.team,
            created_by=self.user,
            name="Test Environment",
        )
        assert env.network_access_level == SandboxEnvironment.NetworkAccessLevel.FULL
        assert env.allowed_domains == []
        assert not env.include_default_domains
        assert env.repositories == []
        assert env.private
        assert env.environment_variables == {}

    def test_environment_variables_encrypted_roundtrip(self):
        env = SandboxEnvironment.objects.create(
            team=self.team,
            created_by=self.user,
            name="Test Environment",
            environment_variables={
                "API_KEY": "sk-live-123456",
                "SECRET_TOKEN": "super-secret-token",
            },
        )

        env.refresh_from_db()
        assert env.environment_variables["API_KEY"] == "sk-live-123456"
        assert env.environment_variables["SECRET_TOKEN"] == "super-secret-token"

    def test_environment_variables_stored_encrypted(self):
        secret_value = "my-super-secret-api-key-12345"
        env = SandboxEnvironment.objects.create(
            team=self.team,
            created_by=self.user,
            name="Test Environment",
            environment_variables={"SECRET": secret_value},
        )

        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT environment_variables FROM posthog_sandbox_environment WHERE id = %s",
                [str(env.id)],
            )
            raw_value = cursor.fetchone()[0]

        assert secret_value not in raw_value

    def test_created_by_set_null_on_user_delete(self):
        env = SandboxEnvironment.objects.create(
            team=self.team,
            created_by=self.user,
            name="Test Environment",
        )

        self.user.delete()
        env.refresh_from_db()
        assert env.created_by is None

    def test_cascade_delete_on_team_delete(self):
        env = SandboxEnvironment.objects.create(
            team=self.team,
            created_by=self.user,
            name="Test Environment",
        )
        env_id = env.id

        self.team.delete()
        assert SandboxEnvironment.objects.filter(id=env_id).count() == 0

    @parameterized.expand(
        [
            ("API_KEY", True),
            ("_PRIVATE_VAR", True),
            ("lowercase_var", True),
            ("123_INVALID", False),
            ("INVALID-VAR", False),
            ("", False),
        ]
    )
    def test_is_valid_env_var_key(self, key, expected_valid):
        assert SandboxEnvironment.is_valid_env_var_key(key) == expected_valid

    @parameterized.expand(
        [
            (SandboxEnvironment.NetworkAccessLevel.FULL, [], False, []),
            (SandboxEnvironment.NetworkAccessLevel.TRUSTED, [], False, ["github.com", "api.github.com"]),
            (SandboxEnvironment.NetworkAccessLevel.CUSTOM, ["custom.com"], False, ["custom.com"]),
            (SandboxEnvironment.NetworkAccessLevel.CUSTOM, ["custom.com"], True, ["custom.com", "github.com"]),
        ]
    )
    def test_get_effective_domains(self, access_level, allowed_domains, include_defaults, expected_contains):
        env = SandboxEnvironment.objects.create(
            team=self.team,
            created_by=self.user,
            name="Test Environment",
            network_access_level=access_level,
            allowed_domains=allowed_domains,
            include_default_domains=include_defaults,
        )
        domains = env.get_effective_domains()
        for expected in expected_contains:
            assert expected in domains

    def test_full_access_returns_empty_list(self):
        env = SandboxEnvironment.objects.create(
            team=self.team,
            created_by=self.user,
            name="Full Access",
            network_access_level=SandboxEnvironment.NetworkAccessLevel.FULL,
        )
        assert env.get_effective_domains() == []

    def test_custom_with_defaults_does_not_duplicate(self):
        env = SandboxEnvironment.objects.create(
            team=self.team,
            created_by=self.user,
            name="Custom + Defaults",
            network_access_level=SandboxEnvironment.NetworkAccessLevel.CUSTOM,
            allowed_domains=["github.com", "custom.io"],
            include_default_domains=True,
        )
        domains = env.get_effective_domains()
        assert domains.count("github.com") == 1
        assert "custom.io" in domains

    def test_custom_without_defaults_returns_only_custom(self):
        env = SandboxEnvironment.objects.create(
            team=self.team,
            created_by=self.user,
            name="Custom Only",
            network_access_level=SandboxEnvironment.NetworkAccessLevel.CUSTOM,
            allowed_domains=["only-this.com"],
            include_default_domains=False,
        )
        assert env.get_effective_domains() == ["only-this.com"]

    def test_trusted_includes_all_default_domains(self):
        from products.tasks.backend.constants import DEFAULT_TRUSTED_DOMAINS

        env = SandboxEnvironment.objects.create(
            team=self.team,
            created_by=self.user,
            name="Trusted",
            network_access_level=SandboxEnvironment.NetworkAccessLevel.TRUSTED,
        )
        assert env.get_effective_domains() == DEFAULT_TRUSTED_DOMAINS


class TestTaskRunGetSandboxEnvironment(TestCase):
    organization: ClassVar[Organization]
    team: ClassVar[Team]
    other_team: ClassVar[Team]
    user: ClassVar[User]
    other_user: ClassVar[User]
    integration: ClassVar[Integration]
    task: ClassVar[Task]

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Test Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Test Team")
        cls.other_team = Team.objects.create(organization=cls.organization, name="Other Team")
        cls.user = User.objects.create(email="creator@posthog.com")
        cls.other_user = User.objects.create(email="other@posthog.com")
        cls.integration = Integration.objects.create(team=cls.team, kind="github")
        cls.task = Task.objects.create(
            team=cls.team,
            created_by=cls.user,
            title="Test Task",
            github_integration=cls.integration,
            repository="org/repo",
        )

    def _create_run(self, sandbox_environment_id=None):
        state = {}
        if sandbox_environment_id:
            state["sandbox_environment_id"] = str(sandbox_environment_id)
        return TaskRun.objects.create(task=self.task, team=self.team, state=state)

    def test_returns_none_when_no_environment_id(self):
        run = self._create_run()
        assert run.get_sandbox_environment() is None

    def test_returns_public_environment_on_same_team(self):
        env = SandboxEnvironment.objects.create(
            team=self.team, name="Public", private=False, created_by=self.other_user
        )
        run = self._create_run(env.id)
        assert run.get_sandbox_environment() == env

    def test_returns_none_for_environment_on_different_team(self):
        env = SandboxEnvironment.objects.create(
            team=self.other_team, name="Other Team Env", private=False, created_by=self.other_user
        )
        run = self._create_run(env.id)
        assert run.get_sandbox_environment() is None

    def test_returns_private_environment_when_creator_matches(self):
        env = SandboxEnvironment.objects.create(team=self.team, name="My Private", private=True, created_by=self.user)
        run = self._create_run(env.id)
        assert run.get_sandbox_environment() == env

    def test_returns_none_for_private_environment_when_creator_differs(self):
        env = SandboxEnvironment.objects.create(
            team=self.team, name="Others Private", private=True, created_by=self.other_user
        )
        run = self._create_run(env.id)
        assert run.get_sandbox_environment() is None

    def test_returns_none_for_private_environment_when_task_creator_is_null(self):
        self.task.created_by = None
        self.task.save()
        env = SandboxEnvironment.objects.create(team=self.team, name="Private", private=True, created_by=self.user)
        run = self._create_run(env.id)
        assert run.get_sandbox_environment() is None

    def test_returns_none_for_private_environment_when_env_creator_is_null(self):
        env = SandboxEnvironment.objects.create(
            team=self.team, name="Private No Creator", private=True, created_by=None
        )
        run = self._create_run(env.id)
        assert run.get_sandbox_environment() is None

    def test_returns_none_for_nonexistent_environment_id(self):
        run = self._create_run(uuid.uuid4())
        assert run.get_sandbox_environment() is None

    def test_returns_none_for_malformed_environment_id(self):
        run = self._create_run("not-a-uuid")
        assert run.get_sandbox_environment() is None


class TestCodeInvite(TestCase):
    def test_auto_generates_code_on_save(self):
        invite = CodeInvite.objects.create()
        assert len(invite.code) == 8
        assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" for c in invite.code)

    def test_preserves_explicit_code(self):
        invite = CodeInvite.objects.create(code="MYCODE42")
        assert invite.code == "MYCODE42"

    def test_retries_on_code_collision(self):
        existing = CodeInvite.objects.create(code="AAAAAAAA")
        assert existing.code == "AAAAAAAA"

        call_count = 0
        original_choice = secrets.choice

        def mock_choice(alphabet):
            nonlocal call_count
            call_count += 1
            # First 8 calls (first attempt) return "A" to collide, rest are random
            if call_count <= 8:
                return "A"
            return original_choice(alphabet)

        with patch("products.tasks.backend.models.secrets.choice", side_effect=mock_choice):
            invite = CodeInvite.objects.create()

        assert invite.code != "AAAAAAAA"
        assert len(invite.code) == 8

    def test_raises_after_max_retries(self):
        CodeInvite.objects.create(code="BBBBBBBB")

        with patch("products.tasks.backend.models.secrets.choice", return_value="B"):
            with self.assertRaises(IntegrityError):
                CodeInvite.objects.create()
