from typing import ClassVar

import unittest
from unittest.mock import patch

from django.test import TestCase

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.models import SlackThreadTaskMapping
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.slack_relay.activities import (
    RelaySlackMessageInput,
    _markdown_to_slack_mrkdwn,
    relay_slack_message,
)


class TestRelaySlackMessage(TestCase):
    org: ClassVar[Organization]
    team: ClassVar[Team]
    user: ClassVar[User]
    integration: ClassVar[Integration]
    task: ClassVar[Task]
    task_run: ClassVar[TaskRun]

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="TestOrg")
        cls.team = Team.objects.create(organization=cls.org, name="TestTeam")
        cls.user = User.objects.create(email="alice@test.com")

        cls.task = Task.objects.create(
            team=cls.team,
            title="Test task",
            description="desc",
            origin_product=Task.OriginProduct.SLACK,
            created_by=cls.user,
            repository="org/repo",
        )
        cls.task_run = TaskRun.objects.create(
            task=cls.task,
            team=cls.team,
            status=TaskRun.Status.IN_PROGRESS,
            state={},
        )
        cls.integration = Integration.objects.create(
            team=cls.team,
            kind="slack",
            integration_id="T123",
            config={},
        )
        SlackThreadTaskMapping.objects.create(
            team=cls.team,
            integration=cls.integration,
            slack_workspace_id="T123",
            channel="C123",
            thread_ts="1111.1",
            task=cls.task,
            task_run=cls.task_run,
            mentioning_slack_user_id="U123",
        )

    @parameterized.expand(
        [
            ("no_reaction_emoji", "relay-1", "Which license should I use?", None),
            ("explicit_reaction_emoji", "relay-2", "Could not deliver follow-up", "x"),
        ]
    )
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.update_reaction")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.post_thread_message")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.delete_progress")
    def test_relay_posts_message_and_marks_sent(
        self,
        _name,
        relay_id,
        text,
        reaction_emoji,
        mock_delete_progress,
        mock_post,
        mock_update,
    ):
        relay_slack_message(
            RelaySlackMessageInput(
                run_id=str(self.task_run.id),
                relay_id=relay_id,
                text=text,
                user_message_ts="1234.5",
                reaction_emoji=reaction_emoji,
            )
        )

        mock_delete_progress.assert_called_once()
        mock_post.assert_called_once()
        assert text in mock_post.call_args.args[0]
        if reaction_emoji is None:
            mock_update.assert_not_called()
        else:
            mock_update.assert_called_once_with(reaction_emoji)
        self.task_run.refresh_from_db()
        assert relay_id in self.task_run.state.get("slack_sent_relay_ids", [])


class TestMarkdownToSlackMrkdwn(unittest.TestCase):
    @parameterized.expand(
        [
            ("bold", "**hello**", "*hello*"),
            ("italic_asterisk", "*italic*", "_italic_"),
            ("italic_underscore", "_italic_", "_italic_"),
            ("bold_italic", "***boldit***", "*_boldit_*"),
            ("strikethrough", "~~removed~~", "~removed~"),
            ("link", "[Click here](https://example.com)", "<https://example.com|Click here>"),
            ("h1", "# Title", "*Title*"),
            ("h3", "### Section", "*Section*"),
            ("dash_bullets", "- one\n- two", "• one\n• two"),
            ("ordered_list_preserved", "1. one\n2. two", "1. one\n2. two"),
            ("task_list", "- [ ] todo\n- [x] done", "• ☐ todo\n• ☑ done"),
            ("horizontal_rule", "---", "──────────"),
            ("blockquote_preserved", "> quote", "> quote"),
            ("nested_bold_in_dash_list", "- **MIT** is permissive", "• *MIT* is permissive"),
            ("plain_text_unchanged", "Hello world", "Hello world"),
            ("inline_code_preserved", "Use `git commit`", "Use `git commit`"),
        ]
    )
    def test_inline_conversions(self, _name, markdown, expected):
        assert _markdown_to_slack_mrkdwn(markdown) == expected

    def test_empty_string_returns_unchanged(self):
        assert _markdown_to_slack_mrkdwn("") == ""
