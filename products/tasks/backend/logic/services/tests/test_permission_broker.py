from types import SimpleNamespace

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from products.tasks.backend.logic.services.permission_broker import (
    parse_permission_request,
    try_auto_respond_permission_request,
)
from products.tasks.backend.models import Task, TaskRun

BROKER = "products.tasks.backend.logic.services.permission_broker"


class TestParsePermissionRequest(SimpleTestCase):
    def test_parses_bare_and_notification_shapes(self) -> None:
        bare = {
            "type": "permission_request",
            "requestId": "perm-1",
            "options": [
                {"kind": "allow_once", "name": "Yes", "optionId": "allow"},
                {"kind": "reject_once", "name": "No", "optionId": "reject"},
            ],
            "toolCall": {"_meta": {"claudeCode": {"toolName": "Bash"}}, "rawInput": {"command": "ls"}},
        }
        notification = {
            "type": "notification",
            "notification": {
                "method": "_posthog/permission_request",
                "params": {key: value for key, value in bare.items() if key != "type"},
            },
        }

        for event in (bare, notification):
            parsed = parse_permission_request(event)
            assert parsed is not None
            assert parsed["request_id"] == "perm-1"
            assert [option["optionId"] for option in parsed["options"]] == ["allow", "reject"]

    def test_rejects_non_permission_events(self) -> None:
        assert parse_permission_request({"type": "notification", "notification": {"method": "other"}}) is None
        assert parse_permission_request({"type": "permission_request", "requestId": "perm-1", "options": []}) is None


class TestTryAutoRespondPermissionRequest(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.task = Task.objects.create(
            team=self.team,
            title="Create a PDF",
            created_by=self.user,
            origin_product=Task.OriginProduct.SLACK,
        )
        self.task_run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            state={"sandbox_url": "https://sandbox.example.com"},
        )

    def _permission_request(self) -> dict:
        parsed = parse_permission_request(
            {
                "type": "permission_request",
                "requestId": "perm-1",
                "toolCall": {
                    "title": "Run tool",
                    "_meta": {"claudeCode": {"toolName": "Bash"}},
                    "rawInput": {"command": "rm -rf /workspace"},
                },
                "options": [
                    {"optionId": "always", "kind": "allow_always", "name": "Always"},
                    {"optionId": "allow", "kind": "allow_once", "name": "Yes"},
                    {"optionId": "reject", "kind": "reject_once", "name": "No"},
                ],
            }
        )
        assert parsed is not None
        return parsed

    def _auto_respond(self, *, send_success: bool = True) -> tuple[bool, MagicMock]:
        with (
            patch(f"{BROKER}.create_sandbox_connection_token", return_value="sandbox-token"),
            patch(
                f"{BROKER}.send_agent_command",
                return_value=SimpleNamespace(
                    success=send_success, status_code=200 if send_success else 502, error=None
                ),
            ) as mock_send,
        ):
            handled = try_auto_respond_permission_request(self.task_run, self._permission_request())
        return handled, mock_send

    def test_slack_run_request_is_allowed_with_default_option(self) -> None:
        handled, mock_send = self._auto_respond()

        assert handled is True
        mock_send.assert_called_once_with(
            self.task_run,
            method="permission_response",
            params={"requestId": "perm-1", "optionId": "allow"},
            auth_token="sandbox-token",
        )

    def test_non_slack_run_is_never_auto_answered(self) -> None:
        self.task.origin_product = Task.OriginProduct.USER_CREATED
        self.task.save(update_fields=["origin_product"])

        handled, mock_send = self._auto_respond()

        assert handled is False
        mock_send.assert_not_called()

    def test_repeated_request_is_deduped(self) -> None:
        self._auto_respond()
        handled, mock_send = self._auto_respond()

        assert handled is True
        mock_send.assert_not_called()

    def test_failed_delivery_does_not_dedupe(self) -> None:
        handled, _ = self._auto_respond(send_success=False)
        assert handled is False

        handled, mock_send = self._auto_respond()
        assert handled is True
        mock_send.assert_called_once()
