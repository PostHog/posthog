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
from products.tasks.backend.logic.services.task_run_user_notification import (
    mirror_user_message_to_slack,
    notify_task_owner,
)
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

        self.slack_client = MagicMock()
        self.slack_client.chat_postMessage.return_value = {"ok": True, "channel": "D-owner", "ts": "100.1"}
        for module in (
            "products.slack_app.backend.services.slack_dm_recipient",
            "products.tasks.backend.logic.services.task_run_user_notification",
        ):
            client_patch = patch(f"{module}.SlackIntegration")
            self.addCleanup(client_patch.stop)
            client_patch.start().return_value.client = self.slack_client

    def _new_run(self) -> TaskRun:
        return TaskRun.objects.create(
            task=self.task, team=self.team, status=TaskRun.Status.IN_PROGRESS, environment=TaskRun.Environment.CLOUD
        )

    def _notify(
        self,
        run: TaskRun | None = None,
        message: str = "Tests pass. I opened the PR.",
        remote_control: bool | None = None,
    ):
        get_tasks_cache().clear()
        return notify_task_owner(
            task_run=run or self.task_run,
            channel=UserNotificationChannel.SLACK,
            reason=UserNotificationReason.UPDATE,
            message=message,
            remote_control=remote_control,
        )

    def _post_kwargs(self, call_index: int = -1) -> dict:
        return self.slack_client.chat_postMessage.call_args_list[call_index].kwargs

    def _footer(self) -> str | None:
        blocks = self._post_kwargs()["attachments"][0]["blocks"]
        return blocks[1]["elements"][0]["text"] if len(blocks) > 1 else None

    def test_a_plain_notification_does_not_turn_on_remote_control(self):
        result = self._notify()

        assert result.result == UserNotificationOutcome.SENT
        assert result.remote_control_active is False
        assert self._post_kwargs()["channel"] == "U-owner"
        assert not SlackThreadTaskMapping.objects.filter(task=self.task).exists()

    def test_remote_control_opens_a_dm_thread_bound_to_the_run(self):
        result = self._notify(remote_control=True)

        assert result.remote_control_active is True
        assert self._post_kwargs()["channel"] == "U-owner"
        assert "Remote control is on" in (self._footer() or "")
        mapping = SlackThreadTaskMapping.objects.get(task_run=self.task_run)
        assert (mapping.channel, mapping.thread_ts, mapping.conversation_type) == ("D-owner", "100.1", "im")
        assert mapping.mentioning_slack_user_id == "U-owner"

    def test_a_new_run_takes_over_remote_control_and_its_first_message_is_mirrored(self):
        self._notify(remote_control=True)

        with self.captureOnCommitCallbacks(execute=True):
            later_run = self.task.create_run(
                extra_state={"pending_user_message": "Also <!here> fix the flaky test"}, acting_user_id=self.user.id
            )

        assert SlackThreadTaskMapping.objects.get(task=self.task).task_run_id == later_run.id
        kwargs = self._post_kwargs()
        assert (kwargs["channel"], kwargs["thread_ts"]) == ("D-owner", "100.1")
        assert "in PostHog Code" in kwargs["text"]
        assert "Also &lt;!here&gt; fix the flaky test" in kwargs["text"]

        self._notify(run=later_run)

        kwargs = self._post_kwargs()
        assert (kwargs["channel"], kwargs["thread_ts"]) == ("D-owner", "100.1")
        assert kwargs["text"].startswith("<@U-owner>")

    def test_a_slack_started_dm_task_is_not_echoed_back_into_its_thread(self):
        self.task.origin_product = Task.OriginProduct.SLACK
        self.task.save()
        SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=self.integration,
            slack_workspace_id=SLACK_WORKSPACE_ID,
            channel="D-owner",
            thread_ts="50.1",
            task=self.task,
            task_run=self.task_run,
            mentioning_slack_user_id="U-owner",
            conversation_type=SlackThreadTaskMapping.ConversationType.IM,
        )

        mirror_user_message_to_slack(
            team_id=self.team.id, task_run_id=str(self.task_run.id), actor_user_id=self.user.id, content="hi"
        )
        later_run = self.task.create_run()

        self.slack_client.chat_postMessage.assert_not_called()
        assert SlackThreadTaskMapping.objects.get(task=self.task).task_run_id == self.task_run.id
        assert later_run.id != self.task_run.id

    def test_remote_control_false_turns_it_off(self):
        self._notify(remote_control=True)

        result = self._notify(remote_control=False)

        assert result.result == UserNotificationOutcome.SENT
        assert result.remote_control_active is False
        assert self._post_kwargs()["thread_ts"] == "100.1"
        assert "Remote control is off" in (self._footer() or "")
        assert not SlackThreadTaskMapping.objects.filter(task=self.task).exists()

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

        result = self._notify(remote_control=True)

        assert result.result == UserNotificationOutcome.NOT_SENT
        self.slack_client.chat_postMessage.assert_not_called()
        assert list(SlackThreadTaskMapping.objects.filter(task=self.task).values_list("channel", flat=True)) == [
            "C-general"
        ]

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
            "products.slack_app.backend.services.slack_dm_recipient.lookup_slack_user_id_by_email", return_value=None
        ):
            first = self._notify()
            second = notify_task_owner(
                task_run=self.task_run,
                channel=UserNotificationChannel.SLACK,
                reason=UserNotificationReason.UPDATE,
                message="again",
            )

        assert first.result == UserNotificationOutcome.NOT_SENT
        assert second.result == UserNotificationOutcome.NOT_SENT
        self.slack_client.chat_postMessage.assert_not_called()

    def test_a_second_notification_inside_the_cooldown_is_throttled(self):
        self._notify()

        result = notify_task_owner(
            task_run=self.task_run,
            channel=UserNotificationChannel.SLACK,
            reason=UserNotificationReason.UPDATE,
            message="again",
        )

        assert result.result == UserNotificationOutcome.THROTTLED
        assert self.slack_client.chat_postMessage.call_count == 1
