import uuid
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.contrib.messages import get_messages

from parameterized import parameterized

from products.tasks.backend.facade.api import accept_desktop_beta_terms, get_desktop_beta_terms_acceptance
from products.tasks.backend.models import Channel, Task, TaskRun

_STORAGE = "products.tasks.backend.logic.services.staff_run_logs.object_storage"
_DOWNLOAD_URL = "/admin/console/tools/task-run-logs/download/"


class TestTaskRunLogsConsoleTool(BaseTest):
    def setUp(self) -> None:
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

    def _download(self, run_id: object) -> Any:
        # A result shows on its own page behind a redirect; a refusal answers directly.
        return self.client.post(_DOWNLOAD_URL, {"run": str(run_id)}, follow=True)

    @patch(f"{_STORAGE}.get_presigned_url", return_value="https://s3.example.test/presigned-link")
    @patch(f"{_STORAGE}.head_object", return_value={"ContentLength": 10})
    def test_shows_a_presigned_download_link(self, _mock_head: MagicMock, mock_presigned: MagicMock) -> None:
        response = self._download(self.task_run.id)

        assert response.status_code == 200
        assert 'href="https://s3.example.test/presigned-link"' in response.content.decode()
        args, kwargs = mock_presigned.call_args
        assert args[0] == self.task_run.log_url
        assert kwargs["content_disposition"] == f'attachment; filename="run_{self.task_run.id}.jsonl"'

    @parameterized.expand(
        [
            ("log_missing", None, "has no logs"),
            ("presign_fails", {"ContentLength": 10}, "Could not create"),
        ]
    )
    @patch(f"{_STORAGE}.get_presigned_url", return_value=None)
    @patch(f"{_STORAGE}.head_object")
    def test_unavailable_log_shows_why(
        self, _name: str, head_result: dict | None, expected: str, mock_head: MagicMock, _mock_presigned: MagicMock
    ) -> None:
        mock_head.return_value = head_result

        response = self._download(self.task_run.id)

        assert response.status_code == 404
        assert expected in " ".join(str(message) for message in get_messages(response.wsgi_request))

    @parameterized.expand([("unknown",), ("private",)])
    @patch(f"{_STORAGE}.head_object")
    def test_unknown_or_private_run_is_refused_without_touching_storage(self, case: str, mock_head: MagicMock) -> None:
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

        run_id = uuid.uuid4() if case == "unknown" else private_run.id

        assert self._download(run_id).status_code == 404
        mock_head.assert_not_called()

    def test_the_old_download_url_opens_the_console_form_for_the_run(self) -> None:
        response = self.client.get(f"/admin/tasks/taskrun/{self.task_run.id}/download-logs/", follow=True)

        assert response.redirect_chain == [(f"{_DOWNLOAD_URL}?run={self.task_run.id}", 302)]
        assert str(self.task_run.id) in response.content.decode()


class TestPostHogDesktopConsolePanel(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    def _revoke(self, data: dict[str, str]) -> Any:
        return self.client.post(
            f"/admin/console/organizations/{self.organization.pk}/posthog-desktop/revoke-beta-terms/", data
        )

    @parameterized.expand(
        [
            ("revokes_with_a_reason", True, {"reason": "Customer asked"}, 302, False),
            ("needs_a_reason", True, {}, 400, True),
            ("not_offered_without_acceptance", False, {"reason": "Customer asked"}, 404, False),
        ]
    )
    def test_revoke_beta_terms(
        self, _name: str, accepted: bool, data: dict[str, str], expected_status: int, accepted_after: bool
    ) -> None:
        if accepted:
            accept_desktop_beta_terms(self.organization.pk, self.user.pk)

        response = self._revoke(data)

        assert response.status_code == expected_status
        assert get_desktop_beta_terms_acceptance(self.organization.pk).is_desktop_beta_terms_accepted == accepted_after
