import uuid

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib.messages import get_messages
from django.urls import reverse

from posthog.admin import register_all_admin

from products.tasks.backend.models import Channel, Loop, Task, TaskRun

register_all_admin()


class TestTaskRunAdminDownloadLogs(BaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)
        self.task = Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
        )
        self.task_run = TaskRun.objects.create(task=self.task, team=self.team)

    @property
    def url(self) -> str:
        return reverse("admin:tasks_taskrun_download_logs", args=[self.task_run.id])

    @property
    def change_url(self) -> str:
        return reverse("admin:tasks_taskrun_change", args=[self.task_run.id])

    @patch("products.tasks.backend.admin.object_storage.get_presigned_url")
    @patch("products.tasks.backend.admin.object_storage.head_object")
    def test_redirects_to_presigned_download_url(self, mock_head, mock_presigned):
        mock_head.return_value = {"ContentLength": 10}
        mock_presigned.return_value = "https://s3.example.test/presigned-link"

        resp = self.client.get(self.url)

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "https://s3.example.test/presigned-link")
        args, kwargs = mock_presigned.call_args
        self.assertEqual(args[0], self.task_run.log_url)
        self.assertEqual(kwargs["content_disposition"], f'attachment; filename="run_{self.task_run.id}.jsonl"')

    @patch("products.tasks.backend.admin.object_storage.get_presigned_url")
    @patch("products.tasks.backend.admin.object_storage.head_object")
    def test_missing_log_redirects_back_without_presigning(self, mock_head, mock_presigned):
        mock_head.return_value = None

        resp = self.client.get(self.url)

        self.assertRedirects(resp, self.change_url, fetch_redirect_response=False)
        mock_presigned.assert_not_called()

    @patch("products.tasks.backend.admin.object_storage.get_presigned_url")
    @patch("products.tasks.backend.admin.object_storage.head_object")
    def test_presign_failure_redirects_back(self, mock_head, mock_presigned):
        mock_head.return_value = {"ContentLength": 10}
        mock_presigned.return_value = None

        resp = self.client.get(self.url)

        self.assertRedirects(resp, self.change_url, fetch_redirect_response=False)

    @patch("products.tasks.backend.admin.object_storage.head_object")
    def test_unknown_run_returns_404(self, mock_head):
        resp = self.client.get(reverse("admin:tasks_taskrun_download_logs", args=[uuid.uuid4()]))

        self.assertEqual(resp.status_code, 404)
        mock_head.assert_not_called()

    def test_other_users_private_space_run_returns_404(self):
        other_user = self._create_user("other@example.com")
        private_channel = Channel.objects.unscoped().create(
            team=self.team,
            name=Channel.PERSONAL_CHANNEL_NAME,
            channel_type=Channel.ChannelType.PERSONAL,
            created_by=other_user,
        )
        private_task = Task.objects.create(
            team=self.team,
            channel=private_channel,
            title="private",
            description="private",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=other_user,
        )
        private_run = TaskRun.objects.create(task=private_task, team=self.team)

        response = self.client.get(reverse("admin:tasks_taskrun_download_logs", args=[private_run.id]))

        self.assertEqual(response.status_code, 404)

    def test_non_staff_cannot_access(self):
        self.user.is_staff = False
        self.user.save()

        resp = self.client.get(self.url)

        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp["Location"])


class TestLoopAdminPauseAction(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)
        self.mock_pause_schedules = patch("products.tasks.backend.loop_lifecycle.pause_loop_schedules").start()
        self.mock_dispatch = patch("products.tasks.backend.loop_lifecycle.dispatch_loop_event").start()
        self.addCleanup(patch.stopall)
        self.enabled = self._loop("enabled")
        self.already_paused = self._loop("already paused", enabled=False)
        self.deleted = self._loop("deleted", deleted=True)
        self.unselected = self._loop("unselected")

    def _loop(self, name: str, **overrides: object) -> Loop:
        fields: dict[str, object] = {
            "team": self.team,
            "created_by": self.user,
            "name": name,
            "instructions": "Summarize",
            "runtime_adapter": "claude",
            "model": "claude-sonnet-5",
            "enabled": True,
        }
        fields.update(overrides)
        return Loop.objects.unscoped().create(**fields)

    def _pause(self, *loops: Loop) -> list[str]:
        resp = self.client.post(
            reverse("admin:tasks_loop_changelist"),
            {"action": "pause_loops", "_selected_action": [str(loop.id) for loop in loops]},
        )
        self.assertEqual(resp.status_code, 302)
        return [notice.message for notice in get_messages(resp.wsgi_request)]

    def _state(self, loop: Loop) -> tuple[bool, str | None]:
        fresh = Loop.objects.unscoped().get(id=loop.id)
        return fresh.enabled, fresh.disabled_reason

    def test_pauses_selected_enabled_loops_only(self) -> None:
        notices = self._pause(self.enabled, self.already_paused, self.deleted)

        self.assertEqual(self._state(self.enabled), (False, "admin_paused"))
        self.assertEqual(self._state(self.already_paused), (False, None))
        self.assertEqual(self._state(self.deleted), (True, None))
        self.assertEqual(self._state(self.unselected), (True, None))
        self.assertEqual([call.args[0].id for call in self.mock_pause_schedules.call_args_list], [self.enabled.id])
        self.mock_dispatch.assert_called_once()
        self.assertEqual(self.mock_dispatch.call_args.args[2]["reason"], "admin_paused")
        self.assertEqual(
            notices,
            ["Paused 1 of 3 selected loop(s). Loops that were already paused or deleted were left unchanged."],
        )

    def test_keeps_going_when_one_loop_fails(self) -> None:
        failing = self._loop("failing")

        def fail_for_failing(loop: Loop, event: str, payload: dict[str, object]) -> None:
            if loop.id == failing.id:
                raise RuntimeError("notifications down")

        self.mock_dispatch.side_effect = fail_for_failing

        notices = self._pause(failing, self.enabled)

        self.assertEqual(self._state(self.enabled), (False, "admin_paused"))
        # pause_loop saves the row before it notifies, so the failing loop is paused even though
        # the action reports it as a failure. The report is deliberately the pessimistic one.
        self.assertEqual(self._state(failing), (False, "admin_paused"))
        self.assertEqual(len(notices), 2)
        self.assertEqual(notices[0], "Paused 1 of 2 selected loop(s).")
        self.assertIn(str(failing.id), notices[1])
