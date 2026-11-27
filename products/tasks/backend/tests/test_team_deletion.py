import uuid

from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings
from django.test import TestCase

from temporalio.service import RPCError, RPCStatusCode

from posthog.models import Organization, Team, User
from posthog.storage import object_storage

from products.tasks.backend.facade.api import (
    delete_organization_task_storage,
    delete_team_task_session_storage_page,
    delete_team_task_storage,
)
from products.tasks.backend.logic.services import storage_deletion
from products.tasks.backend.models import Task, TaskRun

MODULE = "products.tasks.backend.team_deletion"


def _cancellable_client() -> tuple[MagicMock, AsyncMock]:
    cancel = AsyncMock()
    handle = MagicMock()
    handle.cancel = cancel
    client = MagicMock()
    client.get_workflow_handle.return_value = handle
    return client, cancel


class TestCancelTaskWorkflowsOnTeamDelete(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_user(
            email="tasks-team-delete@example.com", first_name="Owner", password="password"
        )

    def _run(self, status: str) -> TaskRun:
        task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Fix the flake",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        return TaskRun.objects.create(task=task, team=self.team, status=status)

    def test_deleting_a_team_stops_only_its_live_run_workflows(self):
        # The rows are collected by CASCADE without ever calling TaskRun.delete(), so the
        # workflow IDs have to be captured in pre_delete or they are unrecoverable.
        live = self._run(TaskRun.Status.IN_PROGRESS)
        queued = self._run(TaskRun.Status.QUEUED)
        self._run(TaskRun.Status.COMPLETED)
        team_id = self.team.pk

        with patch(f"{MODULE}.cancel_task_workflows") as cancel_workflows:
            with self.captureOnCommitCallbacks(execute=True):
                self.team.delete()

        cancel_workflows.assert_called_once()
        called_team_id, workflows = cancel_workflows.call_args.args
        self.assertEqual(called_team_id, team_id)
        self.assertEqual(
            dict(workflows),
            {str(live.id): live.workflow_id, str(queued.id): queued.workflow_id},
        )

    def test_no_temporal_call_when_the_team_has_no_live_runs(self):
        self._run(TaskRun.Status.CANCELLED)

        with patch(f"{MODULE}.cancel_task_workflows") as cancel_workflows:
            with self.captureOnCommitCallbacks(execute=True):
                self.team.delete()

        cancel_workflows.assert_not_called()

    def test_the_run_workflow_is_cancelled(self):
        run = self._run(TaskRun.Status.IN_PROGRESS)
        client, cancel = _cancellable_client()

        with patch("posthog.temporal.common.client.sync_connect", return_value=client):
            with self.captureOnCommitCallbacks(execute=True):
                self.team.delete()

        self.assertEqual(
            [call.args[0] for call in client.get_workflow_handle.call_args_list],
            [run.workflow_id],
        )
        # Cancel rather than terminate: only the workflow's own cancellation path reaps the
        # sandbox, and the rows that would let anything else reap it are already gone.
        self.assertEqual(cancel.await_count, 1)
        # Every call is bounded, so an unreachable frontend cannot burn the caller's budget.
        self.assertTrue(all(call.kwargs.get("rpc_timeout") for call in cancel.await_args_list))

    def test_a_missing_workflow_is_not_reported_as_a_failure(self):
        self._run(TaskRun.Status.IN_PROGRESS)
        client, cancel = _cancellable_client()
        cancel.side_effect = RPCError("no such workflow", RPCStatusCode.NOT_FOUND, b"")

        with patch("posthog.temporal.common.client.sync_connect", return_value=client):
            with self.assertNoLogs(MODULE, level="ERROR"):
                with self.captureOnCommitCallbacks(execute=True):
                    self.team.delete()

        self.assertEqual(cancel.await_count, 1)

    def test_temporal_failures_never_block_the_delete(self):
        run = self._run(TaskRun.Status.IN_PROGRESS)
        team_id = self.team.pk
        client = MagicMock()
        client.get_workflow_handle.side_effect = RuntimeError("temporal unreachable")

        with patch("posthog.temporal.common.client.sync_connect", return_value=client):
            with self.captureOnCommitCallbacks(execute=True):
                self.team.delete()

        self.assertEqual(
            [call.args[0] for call in client.get_workflow_handle.call_args_list],
            [run.workflow_id],
        )
        self.assertFalse(Team.objects.filter(pk=team_id).exists())
        self.assertFalse(TaskRun.objects.filter(id=run.id).exists())


class TestDeleteTaskStorage(TestCase):
    def setUp(self):
        self.team_id = 10_000_001
        self.neighbour_team_id = 100_000_012
        self.organization_id = str(uuid.uuid4())
        self.neighbour_organization_id = str(uuid.uuid4())
        self.written_keys: list[str] = []
        self.enterContext(self.settings(OBJECT_STORAGE_ENABLED=True))
        self.enterContext(patch.object(storage_deletion, "DELETE_BATCH_KEYS_MAX", 2))

    def tearDown(self):
        object_storage.delete_objects(self.written_keys)

    def _write(self, keys: list[str]) -> list[str]:
        for key in keys:
            object_storage.write(key, b"x")
        self.written_keys.extend(keys)
        return keys

    def _write_team_objects(self, team_id: int) -> list[str]:
        folder = settings.OBJECT_STORAGE_TASKS_FOLDER
        return self._write(
            [
                *(f"{folder}/logs/team_{team_id}/task_{task}/run_{task}.jsonl" for task in range(3)),
                f"{folder}/artifacts/team_{team_id}/task_0/run_0/plan.md",
                f"tasks/agent-memory/{team_id}/7/claude/-repo/MEMORY.md",
            ]
        )

    def _write_organization_objects(self, organization_id: str, task_id: str | None = None) -> list[str]:
        task_id = task_id or str(uuid.uuid4())
        return self._write(
            [f"task-sessions/{organization_id}/{task_id}/{uuid.uuid4()}/{part}.jsonl" for part in range(3)]
        )

    def _existing(self, keys: list[str]) -> list[str]:
        return [key for key in keys if object_storage.read_bytes(key, missing_ok=True) is not None]

    def test_deletes_every_page_of_the_team_and_keeps_the_team_sharing_its_id_prefix(self):
        team_keys = self._write_team_objects(self.team_id)
        neighbour_keys = self._write_team_objects(self.neighbour_team_id)

        deleted_count = delete_team_task_storage(self.team_id, should_stop=lambda: False)

        self.assertEqual(deleted_count, len(team_keys))
        self.assertEqual(self._existing(team_keys), [])
        self.assertEqual(self._existing(neighbour_keys), neighbour_keys)

    def test_deletes_the_organization_task_sessions_and_keeps_other_organizations(self):
        organization_keys = self._write_organization_objects(self.organization_id)
        neighbour_keys = self._write_organization_objects(self.neighbour_organization_id)

        deleted_count = delete_organization_task_storage(self.organization_id, should_stop=lambda: False)

        self.assertEqual(deleted_count, len(organization_keys))
        self.assertEqual(self._existing(organization_keys), [])
        self.assertEqual(self._existing(neighbour_keys), neighbour_keys)

    def test_a_key_that_fails_to_delete_raises_instead_of_reporting_the_data_gone(self):
        self._write_team_objects(self.team_id)

        with patch.object(object_storage, "delete_objects", side_effect=lambda keys: keys[:1]):
            with self.assertRaises(storage_deletion.TaskStorageDeletionError):
                delete_team_task_storage(self.team_id, should_stop=lambda: False)

    def test_deletes_the_session_transcripts_of_the_teams_tasks_page_by_page_and_keeps_other_teams(self):
        organization = Organization.objects.create(name="Shared Org")
        user = User.objects.create_user(email="tasks-session-sweep@example.com", first_name="Owner", password="pw")
        deleted_team = Team.objects.create(organization=organization, name="deleted")
        kept_team = Team.objects.create(organization=organization, name="kept")
        deleted_keys: list[str] = []
        kept_keys: list[str] = []
        for team, keys in ((deleted_team, deleted_keys), (deleted_team, deleted_keys), (kept_team, kept_keys)):
            task = Task.objects.create(
                team=team,
                created_by=user,
                title=team.name,
                description="d",
                origin_product=Task.OriginProduct.USER_CREATED,
            )
            TaskRun.objects.create(task=task, team=team)
            keys.extend(self._write_organization_objects(str(organization.id), str(task.id)))

        cursors: list[str] = []
        after_task_id: str | None = None
        for _ in range(4):
            after_task_id = delete_team_task_session_storage_page(
                [deleted_team.pk], after_task_id=after_task_id, limit=1, should_stop=lambda: False
            )
            if after_task_id is None:
                break
            cursors.append(after_task_id)

        self.assertEqual(len(cursors), 2)
        self.assertEqual(self._existing(deleted_keys), [])
        self.assertEqual(self._existing(kept_keys), kept_keys)
