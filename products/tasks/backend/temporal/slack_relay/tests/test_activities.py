from unittest.mock import patch

from django.apps import apps
from django.test import TestCase

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.tasks.backend.temporal.slack_relay.activities import (
    RelaySlackMessageInput,
    _markdown_to_slack_mrkdwn,
    relay_slack_message,
)


class TestRelaySlackMessage(TestCase):
    def setUp(self):
        self.Task = apps.get_model("tasks", "Task")
        self.TaskRun = apps.get_model("tasks", "TaskRun")
        self.SlackThreadTaskMapping = apps.get_model("slack_app", "SlackThreadTaskMapping")
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.user = User.objects.create(email="alice@test.com")

        self.task = self.Task.objects.create(
            team=self.team,
            title="Test task",
            description="desc",
            origin_product=self.Task.OriginProduct.SLACK,
            created_by=self.user,
            repository="org/repo",
        )
        self.task_run = self.TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=self.TaskRun.Status.IN_PROGRESS,
            state={},
        )
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack-twig",
            integration_id="T123",
            config={},
        )
        self.SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=self.integration,
            slack_workspace_id="T123",
            channel="C123",
            thread_ts="1111.1",
            task=self.task,
            task_run=self.task_run,
            mentioning_slack_user_id="U123",
        )

    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.update_reaction")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.post_thread_message")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.delete_progress")
    def test_relay_posts_message_and_marks_sent(self, mock_delete_progress, mock_post, mock_update):
        relay_slack_message(
            RelaySlackMessageInput(
                run_id=str(self.task_run.id),
                relay_id="relay-1",
                text="Which license should I use?",
                user_message_ts="1234.5",
            )
        )

        mock_delete_progress.assert_called_once()
        mock_post.assert_called_once()
        assert "Which license should I use?" in mock_post.call_args.args[0]
        mock_update.assert_called_once_with("white_check_mark")
        self.task_run.refresh_from_db()
        assert "relay-1" in self.task_run.state.get("slack_sent_relay_ids", [])


class TestMarkdownToSlackMrkdwn(TestCase):
    @parameterized.expand(
        [
            ("bold", "**hello**", "*hello*"),
            ("nested_bold_in_list", "- **MIT** is permissive", "- *MIT* is permissive"),
            ("strikethrough", "~~removed~~", "~removed~"),
            ("link", "[Click here](https://example.com)", "<https://example.com|Click here>"),
            ("image", "![alt](https://img.png)", "<https://img.png|alt>"),
            ("h1", "# Title", "*Title*"),
            ("h3", "### Section", "*Section*"),
            ("inline_code_preserved", "Use `git commit`", "Use `git commit`"),
            ("bold_not_in_code", "**bold** and `**not bold**`", "*bold* and `**not bold**`"),
            ("plain_text_unchanged", "Hello world", "Hello world"),
        ]
    )
    def test_inline_conversions(self, _name, markdown, expected):
        assert _markdown_to_slack_mrkdwn(markdown) == expected

    def test_table_converted_to_columns(self):
        md = "| License | Key Points |\n|---|---|\n| **MIT** | Permissive |\n| **GPL** | Copyleft |"
        result = _markdown_to_slack_mrkdwn(md)
        assert "---" not in result
        assert "*MIT*" in result
        assert "*GPL*" in result
        assert "Permissive" in result
        lines = [line for line in result.split("\n") if line.strip()]
        assert len(lines) == 3  # header + 2 data rows

    def test_code_block_preserved(self):
        md = "```python\n**not bold**\n```\nBut **this is bold**"
        result = _markdown_to_slack_mrkdwn(md)
        assert "```python\n**not bold**\n```" in result
        assert "*this is bold*" in result
