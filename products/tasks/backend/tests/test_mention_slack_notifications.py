from unittest.mock import patch

from django.test import TestCase

from slack_sdk.errors import SlackApiError

from posthog.models import Organization, Team, User
from posthog.models.integration import Integration

from products.tasks.backend.models import (
    Channel,
    CodeUserNotificationSettings,
    Task,
    TaskThreadMessage,
    TaskThreadMessageMention,
)
from products.tasks.backend.slack_mention_notifications import send_mention_dms_for_message


class SlackMentionDMTestCase(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Growth Team")
        self.author = User.objects.create_user(email="author@example.com", first_name="Ann", password="password")
        self.peer = User.objects.create_user(email="peer@example.com", first_name="Bob", password="password")
        for user in (self.author, self.peer):
            self.organization.members.add(user)

        # Direct instantiation sidesteps the fail-closed TeamScopedManager so
        # setUp doesn't need a team_scope wrapper (see test_channels_api.py).
        self.channel = Channel(team=self.team, name="growth", created_by=self.author)
        self.channel.save()
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.author,
            channel=self.channel,
            title="A Task",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        self.integration = Integration.objects.create(
            team=self.team, kind="slack", sensitive_config={"access_token": "xoxb-test"}
        )

    def _message(self, content: str, *, mentioned: list[User], author: User | None = ...) -> TaskThreadMessage:  # type: ignore[assignment]
        resolved_author = self.author if author is ... else author
        message = TaskThreadMessage(
            team=self.team,
            task=self.task,
            author=resolved_author,
            author_kind=TaskThreadMessage.AuthorKind.HUMAN if resolved_author else TaskThreadMessage.AuthorKind.AGENT,
            content=content,
        )
        message.save()
        for user in mentioned:
            mention = TaskThreadMessageMention(
                team=self.team, message=message, task=self.task, mentioned_user=user, created_at=message.created_at
            )
            mention.save()
        return message

    def _opt_in(self, user: User) -> None:
        CodeUserNotificationSettings.objects.create(user=user, slack_mention_notifications=True)

    def test_opted_in_recipient_gets_one_dm_with_expected_content(self) -> None:
        self._opt_in(self.peer)
        message = self._message("ping @[Bob](peer@example.com), thoughts?", mentioned=[self.peer])

        with patch("products.tasks.backend.slack_mention_notifications.SlackIntegration") as slack_cls:
            slack = slack_cls.return_value
            slack.lookup_user_id_by_email.return_value = "U123"
            sent = send_mention_dms_for_message(str(message.id), self.team.id)

        assert sent == 1
        slack.lookup_user_id_by_email.assert_called_once_with("peer@example.com")
        slack.client.chat_postMessage.assert_called_once()
        kwargs = slack.client.chat_postMessage.call_args.kwargs
        assert kwargs["channel"] == "U123"
        body = kwargs["blocks"][0]["text"]["text"]
        assert "*Ann*" in body
        assert "*#growth*" in body
        assert "*A Task*" in body
        # Mention tokens render as plain @Name in the excerpt.
        assert "@Bob" in body
        assert "peer@example.com" not in body
        button = kwargs["blocks"][1]["elements"][0]
        assert button["url"].endswith(f"/project/{self.team.id}/tasks/{self.task.id}")

    def test_users_without_opt_in_are_not_dmed(self) -> None:
        # No settings row for peer; author has a row but disabled.
        CodeUserNotificationSettings.objects.create(user=self.author, slack_mention_notifications=False)
        message = self._message("ping @[Bob](peer@example.com)", mentioned=[self.peer, self.author])

        with patch("products.tasks.backend.slack_mention_notifications.SlackIntegration") as slack_cls:
            sent = send_mention_dms_for_message(str(message.id), self.team.id)

        assert sent == 0
        slack_cls.assert_not_called()

    def test_no_slack_integration_is_a_noop(self) -> None:
        self._opt_in(self.peer)
        message = self._message("ping @[Bob](peer@example.com)", mentioned=[self.peer])
        self.integration.delete()

        with patch("products.tasks.backend.slack_mention_notifications.SlackIntegration") as slack_cls:
            sent = send_mention_dms_for_message(str(message.id), self.team.id)

        assert sent == 0
        slack_cls.assert_not_called()

    def test_recipient_without_slack_account_is_skipped(self) -> None:
        self._opt_in(self.peer)
        message = self._message("ping @[Bob](peer@example.com)", mentioned=[self.peer])

        with patch("products.tasks.backend.slack_mention_notifications.SlackIntegration") as slack_cls:
            slack = slack_cls.return_value
            slack.lookup_user_id_by_email.return_value = None
            sent = send_mention_dms_for_message(str(message.id), self.team.id)

        assert sent == 0
        slack.client.chat_postMessage.assert_not_called()

    def test_one_recipient_failure_does_not_block_the_others(self) -> None:
        carol = User.objects.create_user(email="carol@example.com", first_name="Carol", password="password")
        self.organization.members.add(carol)
        self._opt_in(self.peer)
        self._opt_in(carol)
        message = self._message("ping both", mentioned=[self.peer, carol])

        with patch("products.tasks.backend.slack_mention_notifications.SlackIntegration") as slack_cls:
            slack = slack_cls.return_value
            slack.lookup_user_id_by_email.return_value = "U123"
            slack.client.chat_postMessage.side_effect = [
                SlackApiError("boom", {"error": "channel_not_found"}),
                {"ok": True},
            ]
            sent = send_mention_dms_for_message(str(message.id), self.team.id)

        assert sent == 1
        assert slack.client.chat_postMessage.call_count == 2

    def test_agent_author_and_channel_less_task_degrade_gracefully(self) -> None:
        self.task.channel = None
        self.task.save()
        self._opt_in(self.peer)
        message = self._message("done, @[Bob](peer@example.com)", mentioned=[self.peer], author=None)

        with patch("products.tasks.backend.slack_mention_notifications.SlackIntegration") as slack_cls:
            slack = slack_cls.return_value
            slack.lookup_user_id_by_email.return_value = "U123"
            sent = send_mention_dms_for_message(str(message.id), self.team.id)

        assert sent == 1
        body = slack.client.chat_postMessage.call_args.kwargs["blocks"][0]["text"]["text"]
        assert "*PostHog agent* mentioned you\n" in body
        assert "#" not in body

    def test_content_is_escaped_and_truncated(self) -> None:
        self._opt_in(self.peer)
        message = self._message("@[Bob](peer@example.com) see <!channel> & this " + "x" * 400, mentioned=[self.peer])

        with patch("products.tasks.backend.slack_mention_notifications.SlackIntegration") as slack_cls:
            slack = slack_cls.return_value
            slack.lookup_user_id_by_email.return_value = "U123"
            send_mention_dms_for_message(str(message.id), self.team.id)

        body = slack.client.chat_postMessage.call_args.kwargs["blocks"][0]["text"]["text"]
        assert "<!channel>" not in body
        assert "&lt;!channel&gt; &amp; this" in body
        assert body.endswith("…")
