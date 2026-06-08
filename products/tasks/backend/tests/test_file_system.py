from posthog.models import FileSystem
from posthog.models.file_system.constants import DESKTOP_SURFACE, surface_q

from products.tasks.backend.models import Task
from products.tasks.backend.tests.test_api import BaseTaskAPITest


class TestTaskFileSystem(BaseTaskAPITest):
    def _task_rows(self, task: Task):
        return FileSystem.objects.filter(team=self.team, type="task", ref=str(task.id)).exclude(shortcut=True)

    def test_creating_a_task_does_not_file_it(self):
        task = self.create_task(title="My Task")
        self.assertFalse(FileSystem.objects.filter(team=self.team, type="task", ref=str(task.id)).exists())

    def test_file_action_files_task_on_desktop_surface(self):
        task = self.create_task(title="My Task")

        response = self.client.post(f"/api/projects/@current/tasks/{task.id}/file/")
        self.assertEqual(response.status_code, 200, response.content)

        entry = self._task_rows(task).get()
        self.assertEqual(entry.path, "Tasks/My Task")
        self.assertEqual(entry.href, f"/tasks/{task.id}")
        self.assertEqual(entry.surface, DESKTOP_SURFACE)
        self.assertEqual(response.json()["path"], "Tasks/My Task")

        # Never leaks into the web app tree.
        self.assertFalse(
            FileSystem.objects.filter(surface_q("web"), team=self.team, type="task", ref=str(task.id)).exists()
        )

    def test_file_action_into_custom_folder(self):
        task = self.create_task(title="My Task")

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/file/",
            {"folder": "Tasks/Bugs"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self._task_rows(task).get().path, "Tasks/Bugs/My Task")

    def test_file_action_is_idempotent(self):
        task = self.create_task(title="My Task")

        self.client.post(f"/api/projects/@current/tasks/{task.id}/file/")
        self.client.post(f"/api/projects/@current/tasks/{task.id}/file/")

        self.assertEqual(self._task_rows(task).count(), 1)

    def test_unfile_action_removes_entry_but_keeps_task(self):
        task = self.create_task(title="My Task")
        self.client.post(f"/api/projects/@current/tasks/{task.id}/file/")
        self.assertEqual(self._task_rows(task).count(), 1)

        response = self.client.post(f"/api/projects/@current/tasks/{task.id}/unfile/")
        self.assertEqual(response.status_code, 204, response.content)

        self.assertFalse(self._task_rows(task).exists())
        task.refresh_from_db()
        self.assertFalse(task.deleted)

    def test_soft_deleting_a_filed_task_removes_entry(self):
        task = self.create_task(title="My Task")
        self.client.post(f"/api/projects/@current/tasks/{task.id}/file/")
        self.assertEqual(self._task_rows(task).count(), 1)

        task.deleted = True
        task.save()

        self.assertFalse(self._task_rows(task).exists())

    def test_hard_deleting_a_filed_task_removes_entry(self):
        task = self.create_task(title="My Task")
        self.client.post(f"/api/projects/@current/tasks/{task.id}/file/")
        task_id = task.id
        self.assertEqual(FileSystem.objects.filter(team=self.team, type="task", ref=str(task_id)).count(), 1)

        # Task.delete() is blocked; queryset.delete() bypasses the override and fires post_delete.
        Task.objects.filter(pk=task_id).delete()

        self.assertFalse(FileSystem.objects.filter(team=self.team, type="task", ref=str(task_id)).exists())

    def test_unfiled_sweep_does_not_file_tasks(self):
        self.create_task(title="My Task")

        response = self.client.get(f"/api/projects/{self.team.id}/desktop_file_system/unfiled/?type=task")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(FileSystem.objects.filter(team=self.team, type="task").exists())

    def test_tree_delete_and_restore(self):
        task = self.create_task(title="My Task")
        self.client.post(f"/api/projects/@current/tasks/{task.id}/file/")
        entry = self._task_rows(task).get()

        # Deleting the tree entry soft-deletes the task and removes the row.
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
        self.assertEqual(self._task_rows(task).get().path, "Tasks/My Task")

    def test_tree_delete_blocked_for_other_users_task(self):
        # A teammate filed a task they own. The current user (admin or not) must not be able to
        # delete it via the generic file system endpoint, since that would soft-delete the task.
        other_user = self.create_organization_user("victim")
        task = self.create_task(title="Their Task", created_by=other_user)
        self.client.force_authenticate(other_user)
        self.client.post(f"/api/projects/@current/tasks/{task.id}/file/")
        entry = self._task_rows(task).get()

        self.client.force_authenticate(self.user)
        response = self.client.delete(f"/api/projects/{self.team.id}/desktop_file_system/{entry.id}/")

        self.assertEqual(response.status_code, 403, response.content)
        task.refresh_from_db()
        self.assertFalse(task.deleted)
        self.assertTrue(self._task_rows(task).exists())

    def test_tree_undo_blocked_for_other_users_task(self):
        other_user = self.create_organization_user("victim")
        task = self.create_task(title="Their Task", created_by=other_user)
        self.client.force_authenticate(other_user)
        self.client.post(f"/api/projects/@current/tasks/{task.id}/file/")
        entry = self._task_rows(task).get()
        # Soft-delete the task as the owner so undo has something to restore.
        task.deleted = True
        task.save()

        self.client.force_authenticate(self.user)
        undo_response = self.client.post(
            f"/api/projects/{self.team.id}/desktop_file_system/undo_delete/",
            {"items": [{"type": "task", "ref": str(task.id), "path": entry.path}]},
            format="json",
        )

        self.assertEqual(undo_response.status_code, 403, undo_response.content)
        task.refresh_from_db()
        self.assertTrue(task.deleted)
