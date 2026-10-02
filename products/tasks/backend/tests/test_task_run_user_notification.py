from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.user_integration import UserIntegration

from products.slack_app.backend.feature_flags import ASSISTANT_REQUIRED_SCOPES, OAUTH_REQUIRED_SCOPES
from products.slack_app.backend.models import SlackThreadTaskMapping
from products.tasks.backend.facade.contracts import (
    UserNotificationChannel,
    UserNotificationOutcome,
    UserNotificationReason,
)
from products.tasks.backend.logic.services.task_run_user_notification import notify_task_owner
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.redis import get_tasks_cache

SLACK_WORKSPACE_ID = "T123"
ALL_SCOPES = ",".join(sorted(ASSISTANT_REQUIRED_SCOPES | OAUTH_REQUIRED_SCOPES))


class TestTaskRunUserNotification(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        get_tasks_cache().clear()
        self.integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id=SLACK_WORKSPACE_ID, config={"scope": ALL_SCOPES}
        )
        UserIntegration.objects.create(
            user=self.user,
            kind=UserIntegration.IntegrationKind.SLACK,
            integration_id="U-owner",
            config={"slack_team_id": SLACK_WORKSPACE_ID},
        )
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Fix the login redirect",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        self.task_run = self._new_run()

        client_patch = patch("products.tasks.backend.logic.services.slack_dm_recipient.SlackIntegration")
        self.addCleanup(client_patch.stop)
        self.slack_client = MagicMock()
        self.slack_client.chat_postMessage.return_value = {"ok": True, "channel": "D-owner", "ts": "100.1"}
        client_patch.start().return_value.client = self.slack_client

    def _new_run(self) -> TaskRun:
        return TaskRun.objects.create(
            task=self.task, team=self.team, status=TaskRun.Status.IN_PROGRESS, environment=TaskRun.Environment.CLOUD
        )

    def _notify(self, run: TaskRun | None = None, message: str = "Tests pass. I opened the PR."):
        return notify_task_owner(
            task_run=run or self.task_run,
            channel=UserNotificationChannel.SLACK,
            reason=UserNotificationReason.UPDATE,
            message=message,
        )

    def _post_kwargs(self, call_index: int = -1) -> dict:
        return self.slack_client.chat_postMessage.call_args_list[call_index].kwargs

    def test_first_notification_opens_a_dm_thread_that_continues_the_task(self):
        result = self._notify()

        assert result.result == UserNotificationOutcome.SENT
        assert result.replies_continue_task is True
        assert self._post_kwargs()["channel"] == "U-owner"
        assert self._post_kwargs()["thread_ts"] is None
        mapping = SlackThreadTaskMapping.objects.get(task_run=self.task_run)
        assert (mapping.channel, mapping.thread_ts, mapping.conversation_type) == ("D-owner", "100.1", "im")
        assert mapping.mentioning_slack_user_id == "U-owner"

    def test_later_notifications_reply_in_the_owner_thread_and_follow_the_newest_run(self):
        self._notify()
        get_tasks_cache().clear()
        later_run = self._new_run()

        result = self._notify(run=later_run)

        assert result.replies_continue_task is True
        kwargs = self._post_kwargs()
        assert (kwargs["channel"], kwargs["thread_ts"]) == ("D-owner", "100.1")
        assert kwargs["text"].startswith("<@U-owner>")
        mapping = SlackThreadTaskMapping.objects.get(task=self.task)
        assert mapping.task_run_id == later_run.id

    def test_a_run_driven_by_a_channel_thread_keeps_that_thread(self):
        SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=self.integration,
            slack_workspace_id=SLACK_WORKSPACE_ID,
            channel="C-general",
            thread_ts="50.1",
            task=self.task,
            task_run=self.task_run,
            mentioning_slack_user_id="U-owner",
            conversation_type=SlackThreadTaskMapping.ConversationType.PUBLIC_CHANNEL,
        )

        result = self._notify()

        assert result.result == UserNotificationOutcome.SENT
        assert result.replies_continue_task is False
        assert self._post_kwargs()["channel"] == "U-owner"
        assert list(
            SlackThreadTaskMapping.objects.filter(task_run=self.task_run).values_list("channel", flat=True)
        ) == ["C-general"]

    def test_agent_text_cannot_ping_or_disguise_links(self):
        self._notify(message="<!channel> see <https://evil.example.com|the docs>")

        body = self._post_kwargs()["attachments"][0]["blocks"][0]["text"]["text"]
        assert "<!channel>" not in body
        assert "&lt;!channel&gt;" in body
        assert "<https://evil.example.com|" not in body

    @parameterized.expand(
        [
            ("no_slack_install", lambda test: Integration.objects.filter(kind="slack").delete()),
            ("owner_not_in_slack", lambda test: UserIntegration.objects.filter(user=test.user).delete()),
        ]
    )
    def test_an_undelivered_notification_does_not_start_the_cooldown(self, _name, break_delivery):
        break_delivery(self)
        with patch(
            "products.tasks.backend.logic.services.slack_dm_recipient.lookup_slack_user_id_by_email", return_value=None
        ):
            first = self._notify()
            second = self._notify()

        assert first.result == UserNotificationOutcome.NOT_SENT
        assert second.result == UserNotificationOutcome.NOT_SENT
        self.slack_client.chat_postMessage.assert_not_called()

    def test_a_second_notification_inside_the_cooldown_is_throttled(self):
        self._notify()

        result = self._notify()

        assert result.result == UserNotificationOutcome.THROTTLED
        assert self.slack_client.chat_postMessage.call_count == 1
