from posthog.models import FileSystem
from posthog.models.file_system.constants import DESKTOP_SURFACE, surface_q

from products.tasks.backend.models import Task
from products.tasks.backend.tests.test_api import BaseTaskAPITest


class TestTaskFileSystem(BaseTaskAPITest):
    def _task_rows(self, task: Task):
        return FileSystem.objects.filter(team=self.team, type="task", ref=str(task.id)).exclude(shortcut=True)

    def test_creating_a_task_auto_files_it_in_unfiled(self):
        task = self.create_task(title="My Task")
        entry = self._task_rows(task).get()
        self.assertEqual(entry.path, "Unfiled/Tasks/My Task")
        self.assertEqual(entry.surface, DESKTOP_SURFACE)
        self.assertEqual(entry.href, f"/tasks/{task.id}")

    def test_task_rows_never_leak_to_web_surface(self):
        task = self.create_task(title="My Task")
        self.assertFalse(
            FileSystem.objects.filter(surface_q("web"), team=self.team, type="task", ref=str(task.id)).exists()
        )

    def test_renaming_task_renames_all_filed_rows(self):
        task = self.create_task(title="My Task")
        # Simulate filing to a channel by creating a second row directly under a channel folder.
        FileSystem.objects.create(
            team=self.team,
            path="Channels/Engineering/My Task",
            depth=3,
            type="task",
            ref=str(task.id),
            href=f"/tasks/{task.id}",
            meta={},
            shortcut=False,
            surface=DESKTOP_SURFACE,
            created_by=self.user,
        )
        task.title = "Renamed"
        task.save()

        paths = sorted(self._task_rows(task).values_list("path", flat=True))
        self.assertEqual(paths, ["Channels/Engineering/Renamed", "Unfiled/Tasks/Renamed"])

    def test_soft_delete_removes_all_rows(self):
        task = self.create_task(title="My Task")
        FileSystem.objects.create(
            team=self.team,
            path="Channels/Engineering/My Task",
            depth=3,
            type="task",
            ref=str(task.id),
            href=f"/tasks/{task.id}",
            meta={},
            shortcut=False,
            surface=DESKTOP_SURFACE,
            created_by=self.user,
        )
        self.assertEqual(self._task_rows(task).count(), 2)

        task.deleted = True
        task.save()

        self.assertFalse(self._task_rows(task).exists())

    def test_hard_delete_removes_all_rows(self):
        task = self.create_task(title="My Task")
        task_id = task.id
        self.assertEqual(self._task_rows(task).count(), 1)

        Task.objects.filter(pk=task_id).delete()

        self.assertFalse(FileSystem.objects.filter(team=self.team, type="task", ref=str(task_id)).exists())

    def test_unfiled_sweep_files_existing_tasks(self):
        # Older tasks created before the home row existed can be backfilled via the unfiled sweep.
        task = self.create_task(title="My Task")
        self._task_rows(task).delete()
        self.assertFalse(self._task_rows(task).exists())

        response = self.client.get(f"/api/projects/{self.team.id}/desktop_file_system/unfiled/?type=task")
        self.assertEqual(response.status_code, 200, response.content)

        entry = self._task_rows(task).get()
        self.assertEqual(entry.path, "Unfiled/Tasks/My Task")

    def test_deleting_one_of_many_rows_preserves_task(self):
        task = self.create_task(title="My Task")
        channel_row = FileSystem.objects.create(
            team=self.team,
            path="Channels/Engineering/My Task",
            depth=3,
            type="task",
            ref=str(task.id),
            href=f"/tasks/{task.id}",
            meta={},
            shortcut=False,
            surface=DESKTOP_SURFACE,
            created_by=self.user,
        )

        # Removing one row (e.g. unfiling from a channel) leaves the task and the home row alone.
        response = self.client.delete(f"/api/projects/{self.team.id}/desktop_file_system/{channel_row.id}/")
        self.assertEqual(response.status_code, 204, response.content)
        task.refresh_from_db()
        self.assertFalse(task.deleted)
        self.assertEqual(self._task_rows(task).get().path, "Unfiled/Tasks/My Task")

    def test_deleting_last_row_soft_deletes_task(self):
        task = self.create_task(title="My Task")
        entry = self._task_rows(task).get()

        # Removing the last remaining row treats the file-system action as a delete of the task itself.
        delete_response = self.client.delete(f"/api/projects/{self.team.id}/desktop_file_system/{entry.id}/")
        self.assertEqual(delete_response.status_code, 200, delete_response.content)
        task.refresh_from_db()
        self.assertTrue(task.deleted)
        self.assertFalse(self._task_rows(task).exists())

        # Undo restores the task and recreates the row.
        undo_response = self.client.post(
            f"/api/projects/{self.team.id}/desktop_file_system/undo_delete/",
            {"items": [{"type": "task", "ref": str(task.id), "path": entry.path}]},
            format="json",
        )
        self.assertEqual(undo_response.status_code, 200, undo_response.content)
        task.refresh_from_db()
        self.assertFalse(task.deleted)
        self.assertEqual(self._task_rows(task).get().path, "Unfiled/Tasks/My Task")

    def test_tree_delete_blocked_for_other_users_task(self):
        # A teammate owns a task. The current user must not be able to delete it via the
        # generic file system endpoint, since the last-row delete would soft-delete the task.
        other_user = self.create_organization_user("victim")
        task = self.create_task(title="Their Task", created_by=other_user)
        entry = self._task_rows(task).get()

        response = self.client.delete(f"/api/projects/{self.team.id}/desktop_file_system/{entry.id}/")

        self.assertEqual(response.status_code, 403, response.content)
        task.refresh_from_db()
        self.assertFalse(task.deleted)
        self.assertTrue(self._task_rows(task).exists())

    def test_tree_undo_blocked_for_other_users_task(self):
        other_user = self.create_organization_user("victim")
        task = self.create_task(title="Their Task", created_by=other_user)
        entry = self._task_rows(task).get()
        # Soft-delete the task as the owner so undo has something to restore.
        task.deleted = True
        task.save()

        undo_response = self.client.post(
            f"/api/projects/{self.team.id}/desktop_file_system/undo_delete/",
            {"items": [{"type": "task", "ref": str(task.id), "path": entry.path}]},
            format="json",
        )

        self.assertEqual(undo_response.status_code, 403, undo_response.content)
        task.refresh_from_db()
        self.assertTrue(task.deleted)
