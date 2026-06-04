from typing import ClassVar

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
    SLACK_MESSAGE_TEXT_LIMIT,
    RelaySlackMessageInput,
    _markdown_to_slack_mrkdwn,
    _split_text_for_slack,
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


class TestSplitTextForSlack(TestCase):
    def test_short_text_returns_single_chunk(self):
        assert _split_text_for_slack("hello world") == ["hello world"]

    def test_each_chunk_under_limit(self):
        paragraph = ("word " * 200).strip()
        text = "\n\n".join([paragraph] * 10)
        chunks = _split_text_for_slack(text)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= SLACK_MESSAGE_TEXT_LIMIT

    def test_split_prefers_paragraph_boundary(self):
        paragraph = ("alpha " * 400).strip()  # ~2400 chars per paragraph
        text = f"{paragraph}\n\n{paragraph}"
        chunks = _split_text_for_slack(text)
        assert len(chunks) == 2
        assert chunks[0] == paragraph
        assert chunks[1] == paragraph

    def test_split_falls_back_to_line_within_paragraph(self):
        line = ("alpha " * 100).strip()  # ~600 chars
        text = "\n".join([line] * 10)  # single paragraph, ~6000 chars
        chunks = _split_text_for_slack(text)
        assert len(chunks) >= 2
        for chunk in chunks:
            for chunk_line in chunk.split("\n"):
                assert chunk_line == line

    def test_hard_breaks_single_long_line(self):
        line = "x" * (SLACK_MESSAGE_TEXT_LIMIT + 500)
        chunks = _split_text_for_slack(line)
        assert len(chunks) == 2
        assert all(len(chunk) <= SLACK_MESSAGE_TEXT_LIMIT for chunk in chunks)
        assert "".join(chunks) == line

    def test_oversized_code_block_keeps_fences_balanced(self):
        body_lines = [f"line {i:04d}" for i in range(800)]
        body = "\n".join(body_lines)
        text = f"```python\n{body}\n```"
        chunks = _split_text_for_slack(text)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert chunk.startswith("```python\n")
            assert chunk.endswith("\n```")
            assert chunk.count("```") == 2
            assert len(chunk) <= SLACK_MESSAGE_TEXT_LIMIT

    def test_mixed_text_and_code_block_preserves_block(self):
        prefix = "intro paragraph\n\n"
        suffix = "\n\ntrailing paragraph"
        code = "```js\n" + "console.log('hi');\n" * 10 + "```"
        text = prefix + code + suffix
        chunks = _split_text_for_slack(text)
        joined = "\n\n".join(chunks)
        assert "```js\n" in joined
        assert joined.count("```") % 2 == 0


class TestRelaySlackMessageChunking(TestCase):
    org: ClassVar[Organization]
    team: ClassVar[Team]
    user: ClassVar[User]
    integration: ClassVar[Integration]
    task: ClassVar[Task]
    task_run: ClassVar[TaskRun]

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="ChunkOrg")
        cls.team = Team.objects.create(organization=cls.org, name="ChunkTeam")
        cls.user = User.objects.create(email="bob@test.com")
        cls.task = Task.objects.create(
            team=cls.team,
            title="Chunk task",
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
            integration_id="T456",
            config={},
        )
        SlackThreadTaskMapping.objects.create(
            team=cls.team,
            integration=cls.integration,
            slack_workspace_id="T456",
            channel="C456",
            thread_ts="2222.2",
            task=cls.task,
            task_run=cls.task_run,
            mentioning_slack_user_id="U456",
        )

    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.update_reaction")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.post_thread_message")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.delete_progress")
    def test_long_text_posts_multiple_chunks_with_prefix_only_on_first(
        self,
        mock_delete_progress,
        mock_post,
        mock_update,
    ):
        paragraph = ("alpha " * 400).strip()
        text = "\n\n".join([paragraph] * 4)
        relay_slack_message(
            RelaySlackMessageInput(
                run_id=str(self.task_run.id),
                relay_id="relay-chunked",
                text=text,
                user_message_ts="1234.5",
                reaction_emoji="hedgehog",
            )
        )

        mock_delete_progress.assert_called_once()
        assert mock_post.call_count >= 2
        first_posted = mock_post.call_args_list[0].args[0]
        assert first_posted.startswith("<@U456> ")
        for call in mock_post.call_args_list[1:]:
            assert not call.args[0].startswith("<@U456>")
        mock_update.assert_called_once_with("hedgehog")

        self.task_run.refresh_from_db()
        assert "relay-chunked" in self.task_run.state.get("slack_sent_relay_ids", [])
