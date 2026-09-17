import uuid

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib import admin
from django.test import RequestFactory
from django.urls import reverse

from parameterized import parameterized

from posthog.admin import register_all_admin
from posthog.models.team.team import Team

from products.tasks.backend.models import Channel, Task, TaskRun, TeamTasksConfig, UserTasksConfig

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


class TestTasksConfigAdminForms(BaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        request = RequestFactory().get("/")
        request.user = self.user
        self.team_form_class = admin.site._registry[TeamTasksConfig].get_form(request)
        self.user_form_class = admin.site._registry[UserTasksConfig].get_form(request)

    @parameterized.expand(
        [
            ("model_without_adapter", {"model": "claude-opus-4-8"}),
            ("unknown_key", {"runtime_adapter": "claude", "model": "claude-opus-4-8", "profile": "max"}),
            ("non_string_value", {"runtime_adapter": "claude", "model": 7}),
        ]
    )
    def test_rejects_invalid_preference_payloads(self, _name: str, payload: dict) -> None:
        form = self.team_form_class(data={"team": self.team.pk, "ai_run_preferences": payload})
        assert not form.is_valid()
        assert "ai_run_preferences" in form.errors

    def test_accepts_a_valid_payload_on_both_admin_forms(self) -> None:
        # The extension row is auto-created with the team, so the admin flow is a change form.
        team_form = self.team_form_class(
            instance=TeamTasksConfig.objects.get(team=self.team),
            data={
                "team": self.team.pk,
                "ai_run_preferences": {"runtime_adapter": "claude", "model": "claude-opus-4-8"},
            },
        )
        assert team_form.is_valid(), team_form.errors
        user_form = self.user_form_class(data={"team": self.team.pk, "user": self.user.pk, "ai_run_preferences": {}})
        assert user_form.is_valid(), user_form.errors

    def test_rejects_a_row_keyed_on_an_environment_team(self) -> None:
        env_team = Team.objects.create(
            organization=self.organization, project=self.project, parent_team=self.team, name="env"
        )
        form = self.team_form_class(data={"team": env_team.pk, "ai_run_preferences": None})
        assert not form.is_valid()
        assert "project root team" in str(form.errors["team"])
