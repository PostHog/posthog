import uuid
from datetime import UTC, datetime
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.contrib.auth.models import Group
from django.contrib.messages import get_messages

from parameterized import parameterized
from temporalio.client import WorkflowExecutionStatus
from temporalio.exceptions import WorkflowAlreadyStartedError

from products.tasks.backend.facade.api import accept_desktop_beta_terms, get_desktop_beta_terms_acceptance
from products.tasks.backend.facade.orphaned_objects import KIND_NAMES
from products.tasks.backend.logic.services.orphaned_objects_runs import TOTALS_MEMO_KEY
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


_ORPHANED_STAFF = "products.tasks.backend.logic.services.orphaned_objects_runs"
_ORPHANED_URL = "/admin/console/tools/orphaned-task-objects/"


class FakeExecution:
    id = "delete-orphaned-task-objects-1"
    run_id = "run-1"
    status = WorkflowExecutionStatus.COMPLETED
    start_time = datetime(2026, 1, 1, tzinfo=UTC)

    async def memo(self) -> dict[str, object]:
        totals = {"prefixes": 12, "objects": 1234, "size_bytes": 2048, "failed_objects": 2, "errored_prefixes": 1}
        return {"execute": True, "kinds": ["logs"], "max_prefixes": 50, TOTALS_MEMO_KEY: totals}


class TestOrphanedTaskObjectsConsoleTool(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)
        self.temporal = MagicMock()
        self.temporal.start_workflow = AsyncMock()
        self.enterContext(patch(f"{_ORPHANED_STAFF}.sync_connect", return_value=self.temporal))

    def _run(self, operation: str, data: dict[str, str], form_nonce: str | None = None) -> Any:
        return self.client.post(f"{_ORPHANED_URL}{operation}/", {**data, "form_nonce": form_nonce or str(uuid.uuid4())})

    @parameterized.expand(
        [
            (
                "scan_starts_a_dry_run",
                "scan",
                False,
                {"kind": "logs", "max_prefixes": "10"},
                302,
                (False, ["logs"], 10),
            ),
            ("scan_needs_a_limit", "scan", False, {"kind": "logs"}, 400, None),
            (
                "delete_starts_a_deletion",
                "delete",
                True,
                {"kind": "all", "max_prefixes": "5", "reason": "Teams were deleted"},
                302,
                (True, list(KIND_NAMES), 5),
            ),
            ("delete_needs_a_reason", "delete", True, {"kind": "all", "max_prefixes": "5"}, 400, None),
            (
                "delete_is_only_for_the_owning_team",
                "delete",
                False,
                {"kind": "all", "max_prefixes": "5", "reason": "Teams were deleted"},
                403,
                None,
            ),
        ]
    )
    def test_operations(
        self,
        _name: str,
        operation: str,
        in_owning_team: bool,
        data: dict[str, str],
        expected_status: int,
        expected_input: tuple[bool, list[str], int] | None,
    ) -> None:
        if in_owning_team:
            self.user.groups.add(Group.objects.get_or_create(name="Agent Infrastructure Team")[0])

        response = self._run(operation, data)

        assert response.status_code == expected_status
        if expected_input is None:
            self.temporal.start_workflow.assert_not_called()
        else:
            workflow_input = self.temporal.start_workflow.call_args.args[1]
            assert (workflow_input.execute, workflow_input.kinds, workflow_input.max_prefixes) == expected_input

    def test_a_double_submit_starts_one_run(self) -> None:
        form_nonce = str(uuid.uuid4())
        self._run("scan", {"kind": "logs", "max_prefixes": "10"}, form_nonce)
        self.temporal.start_workflow.side_effect = WorkflowAlreadyStartedError("id", "type")

        response = self._run("scan", {"kind": "logs", "max_prefixes": "10"}, form_nonce)

        first, second = self.temporal.start_workflow.call_args_list
        assert first.kwargs["id"] == second.kwargs["id"]
        assert "No new run started" in " ".join(str(message) for message in get_messages(response.wsgi_request))

    def test_the_page_lists_recent_runs(self) -> None:
        async def list_workflows(query: str, limit: int, rpc_timeout: object) -> Any:
            yield FakeExecution()

        temporal = MagicMock()
        temporal.list_workflows = list_workflows
        with patch(f"{_ORPHANED_STAFF}.async_connect", AsyncMock(return_value=temporal)):
            content = self.client.get(_ORPHANED_URL).content.decode()

        assert "delete-orphaned-task-objects-1/run-1" in content
        for text in ("2026-01-01 00:00", "Delete", "Task run logs", "12 of 50", "1,234", "2.0\xa0KB", "3"):
            assert text in content
