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
from products.tasks.backend.models import Task, TaskArtifact, TaskRun
from products.tasks.backend.temporal.slack_relay.activities import (
    SLACK_MESSAGE_TEXT_LIMIT,
    RelaySlackMessageInput,
    _append_unconfirmed_attachment_notice,
    _markdown_to_slack_mrkdwn,
    _neutralize_approx_tildes,
    _repair_link_trailing_markers,
    _split_markdown_for_slack,
    _wrap_bare_urls_in_emphasis,
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

    def setUp(self):
        self.task_run.artifacts = []
        self.task_run.state = {}
        self.task_run.save(update_fields=["artifacts", "state", "updated_at"])
        SlackThreadTaskMapping.objects.filter(task_run=self.task_run).update(latest_actor_slack_user_id=None)

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

    @parameterized.expand(
        [
            # ``mentioning_slack_user_id`` is the immutable thread creator;
            # ``latest_actor_slack_user_id`` is set by the follow-up handler
            # when someone else (or the creator themselves) replies. The bot
            # tags the latest actor when present, otherwise the creator.
            ("no_actor_falls_back_to_mentioner", None, "<@U123> "),
            ("actor_overrides_mentioner", "UBOB", "<@UBOB> "),
        ]
    )
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.update_reaction")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.post_thread_message")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.delete_progress")
    def test_mention_prefix_uses_latest_actor_then_mentioner(
        self,
        _name,
        latest_actor,
        expected_prefix,
        _mock_delete_progress,
        mock_post,
        _mock_update,
    ):
        SlackThreadTaskMapping.objects.filter(task_run=self.task_run).update(latest_actor_slack_user_id=latest_actor)

        relay_slack_message(
            RelaySlackMessageInput(
                run_id=str(self.task_run.id),
                relay_id=f"relay-mention-{_name}",
                text="agent reply",
            )
        )

        mock_post.assert_called_once()
        assert mock_post.call_args.args[0].startswith(expected_prefix)

    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.update_reaction")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.post_thread_message")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.delete_progress")
    def test_unconfirmed_attachment_claim_gets_notice(
        self,
        _mock_delete_progress,
        mock_post,
        _mock_update,
    ):
        relay_slack_message(
            RelaySlackMessageInput(
                run_id=str(self.task_run.id),
                relay_id="relay-unconfirmed-attachment",
                text=(
                    "Done. I generated **user_activity_report.pdf** "
                    "at /tmp/workspace/user_activity_report.pdf and it's attached for you."
                ),
            )
        )

        mock_post.assert_called_once()
        posted = mock_post.call_args.args[0]
        assert "user_activity_report.pdf" in posted
        assert "no file was attached to Slack for this run" in posted

    @patch("posthog.storage.object_storage.get_presigned_url", return_value="https://example.com/report.pdf")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.update_reaction")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.post_thread_message")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.delete_progress")
    def test_confirmed_artifact_claim_does_not_get_notice(
        self,
        _mock_delete_progress,
        mock_post,
        _mock_update,
        mock_presign,
    ):
        self.task_run.artifacts = [
            {
                "id": "artifact-1",
                "name": "user_activity_report.pdf",
                "type": "artifact",
                "storage_path": "tasks/artifacts/report.pdf",
            }
        ]
        self.task_run.save(update_fields=["artifacts", "updated_at"])

        relay_slack_message(
            RelaySlackMessageInput(
                run_id=str(self.task_run.id),
                relay_id="relay-confirmed-attachment",
                text="Done. user_activity_report.pdf is attached.",
            )
        )

        mock_post.assert_called_once()
        posted = mock_post.call_args.args[0]
        assert "no file was attached to Slack for this run" not in posted
        assert "<https://example.com/report.pdf|user_activity_report.pdf>" in posted
        mock_presign.assert_called_once_with("tasks/artifacts/report.pdf")

    @patch("products.tasks.backend.logic.services.living_artifacts.requests.post")
    @patch("products.tasks.backend.logic.services.living_artifacts.object_storage.read_bytes")
    @patch("products.tasks.backend.logic.services.living_artifacts._slack_integration_for_mapping")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.update_reaction")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.post_thread_message")
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.delete_progress")
    def test_pending_slack_file_upload_uses_final_message(
        self,
        mock_delete_progress,
        mock_post,
        _mock_update,
        mock_integration_for_mapping,
        mock_read_bytes,
        mock_requests_post,
    ):
        storage_path = f"tasks/artifacts/team_{self.team.id}/task_{self.task.id}/run_{self.task_run.id}/report.v1.xlsx"
        location = {
            "kind": "slack_file",
            "integration_id": self.integration.id,
            "channel": "C123",
            "thread_ts": "1111.1",
            "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "storage_path": storage_path,
            "delivery_status": "pending",
        }
        artifact = TaskArtifact.objects.for_team(self.team.id).create(
            team=self.team,
            task=self.task,
            task_run=self.task_run,
            created_by=self.user,
            name="report.xlsx",
            artifact_type=TaskArtifact.ArtifactType.SPREADSHEET,
            adapter=TaskArtifact.Adapter.SLACK_FILE,
            status=TaskArtifact.Status.ACTIVE,
            location=location,
            metadata={"delivery_status": "pending"},
            versions=[
                {
                    "version": 1,
                    "run_id": str(self.task_run.id),
                    "adapter": TaskArtifact.Adapter.SLACK_FILE,
                    "location": location,
                    "content_type": location["content_type"],
                    "size": 14,
                    "delivery_status": "pending",
                }
            ],
            current_version=1,
        )
        slack = unittest.mock.MagicMock()
        slack.api_call.side_effect = [
            {"upload_url": "https://files.slack.test/upload", "file_id": "F123"},
            {"files": [{"id": "F123", "title": "report.xlsx", "permalink": "https://slack.test/files/F123"}]},
        ]
        slack_integration = unittest.mock.MagicMock()
        slack_integration.client = slack
        slack_integration.missing_scopes.return_value = set()
        mock_integration_for_mapping.return_value = slack_integration
        mock_read_bytes.return_value = b"workbook bytes"

        relay_slack_message(
            RelaySlackMessageInput(
                run_id=str(self.task_run.id),
                relay_id="relay-with-file",
                text="Done. report.xlsx is attached.",
            )
        )

        mock_delete_progress.assert_called_once()
        mock_post.assert_not_called()
        mock_read_bytes.assert_called_once_with(storage_path, missing_ok=True)
        self.assertEqual(mock_requests_post.call_args.kwargs["data"], b"workbook bytes")
        complete_payload = slack.api_call.call_args_list[1].kwargs["data"]
        self.assertEqual(complete_payload["channel_id"], "C123")
        self.assertEqual(complete_payload["thread_ts"], "1111.1")
        self.assertIn("<@U123> Done. report.xlsx is attached.", complete_payload["initial_comment"])
        self.assertNotIn("no file was attached to Slack", complete_payload["initial_comment"])

        artifact.refresh_from_db()
        self.assertEqual(artifact.location["delivery_status"], "delivered")
        self.assertEqual(artifact.location["file_id"], "F123")
        self.assertEqual(artifact.metadata["slack_file_permalink"], "https://slack.test/files/F123")
        self.assertEqual(artifact.versions[0]["delivery_status"], "delivered")
        self.assertEqual(artifact.versions[0]["slack_file_id"], "F123")


class TestMarkdownToSlackMrkdwn(unittest.TestCase):
    @parameterized.expand(
        [
            ("bold", "**hello**", "*hello*"),
            ("italic_asterisk", "*italic*", "_italic_"),
            ("italic_underscore", "_italic_", "_italic_"),
            ("bold_italic", "***boldit***", "*_boldit_*"),
            ("strikethrough", "~~removed~~", "~removed~"),
            # "Approximately" tildes in front of a quantity would otherwise pair up as
            # Slack strikethrough delimiters and strike through the text between them.
            # The tilde operator (∼) looks the same but carries no formatting meaning.
            (
                "approx_tildes_do_not_strike_through",
                "**~$36.0k**, averaging **~$5.1k/day** by ~2pm",
                "*∼$36.0k*, averaging *∼$5.1k/day* by ∼2pm",
            ),
            ("link", "[Click here](https://example.com)", "<https://example.com|Click here>"),
            ("h1", "# Title", "*Title*"),
            ("h3", "### Section", "*Section*"),
            ("dash_bullets", "- one\n- two", "• one\n• two"),
            ("ordered_list_preserved", "1. one\n2. two", "1. one\n2. two"),
            ("task_list", "- [ ] todo\n- [x] done", "• ☐ todo\n• ☑ done"),
            ("horizontal_rule", "---", "──────────"),
            ("blockquote_preserved", "> quote", "> quote"),
            ("nested_bold_in_dash_list", "- **MIT** is permissive", "• *MIT* is permissive"),
            (
                "bold_markdown_link",
                "**[pr-shepherd](https://us.posthog.com/project/2/llm-analytics/skills/pr-shepherd)**",
                "*<https://us.posthog.com/project/2/llm-analytics/skills/pr-shepherd|pr-shepherd>*",
            ),
            # Agent emits double-asterisk closing markers inside the angle brackets
            # (`**<url**>`). Without the repair pass the converter would halve those
            # asterisks in place and produce `*<url*>`, which Slack renders as
            # literal text with no link and no bold.
            (
                "agent_typo_double_asterisk_autolink",
                "**<https://us.posthog.com/project/2/llm-analytics/skills/pr-shepherd**>",
                "*<https://us.posthog.com/project/2/llm-analytics/skills/pr-shepherd>*",
            ),
            (
                "agent_typo_double_asterisk_labeled_link",
                "**<https://us.posthog.com/project/2/llm-analytics/skills/pr-shepherd|pr-shepherd**>",
                "*<https://us.posthog.com/project/2/llm-analytics/skills/pr-shepherd|pr-shepherd>*",
            ),
            # Bare URL wrapped directly in markdown bold. Without the pre-wrap pass the
            # converter halves the markers in place and emits ``*https://x.com*``, which
            # Slack renders as literal asterisks around an auto-linked URL — the exact
            # papercut on the PR-completion message that prompted this repair.
            (
                "agent_typo_bare_url_in_bold",
                "Draft PR opened: **https://github.com/PostHog/posthog.com/pull/17450**",
                "Draft PR opened: *<https://github.com/PostHog/posthog.com/pull/17450>*",
            ),
            (
                "agent_typo_bare_url_in_italic_asterisk",
                "see *https://example.com*",
                "see _<https://example.com>_",
            ),
            ("plain_text_unchanged", "Hello world", "Hello world"),
            ("inline_code_preserved", "Use `git commit`", "Use `git commit`"),
        ]
    )
    def test_inline_conversions(self, _name, markdown, expected):
        assert _markdown_to_slack_mrkdwn(markdown) == expected

    def test_empty_string_returns_unchanged(self):
        assert _markdown_to_slack_mrkdwn("") == ""

    def test_table_renders_as_fenced_code_block_with_aligned_columns(self):
        md = "| License | Key Points |\n|---|---|\n| MIT | Permissive |\n| GPL | Copyleft |"
        # Widest cells per column: 'License' (7) and 'Key Points' (10). Two-space gutter.
        # Trailing whitespace is rstripped, so the GPL row's narrower last cell isn't padded.
        expected = "```\nLicense  Key Points\nMIT      Permissive\nGPL      Copyleft\n```"
        assert _markdown_to_slack_mrkdwn(md) == expected

    def test_table_strips_inline_markdown_from_cells(self):
        md = "| Name | Note |\n|---|---|\n| **MIT** | [docs](https://x.com) |"
        result = _markdown_to_slack_mrkdwn(md)
        # Bold markers and link syntax don't render inside a code block, so we strip them.
        assert "**" not in result
        assert "MIT" in result
        assert "docs" in result
        assert "https://x.com" not in result

    def test_pipe_rows_without_separator_are_not_treated_as_a_table(self):
        # No separator row → likely incidental pipes, not a table. Leave alone.
        md = "| a | b |\n| c | d |"
        result = _markdown_to_slack_mrkdwn(md)
        assert "```" not in result


class TestRepairLinkTrailingMarkers(unittest.TestCase):
    @parameterized.expand(
        [
            ("autolink_double_asterisk", "**<https://x.com**>", "**<https://x.com>**"),
            ("autolink_single_asterisk", "*<https://x.com*>", "*<https://x.com>*"),
            ("autolink_underscore", "_<https://x.com_>", "_<https://x.com>_"),
            ("autolink_strikethrough", "~<https://x.com~>", "~<https://x.com>~"),
            (
                "labeled_link_double_asterisk",
                "**<https://x.com|label**>",
                "**<https://x.com|label>**",
            ),
            (
                "two_broken_links_in_one_line",
                "**<https://a.com**> and **<https://b.com**>",
                "**<https://a.com>** and **<https://b.com>**",
            ),
            ("well_formed_autolink_unchanged", "**<https://x.com>**", "**<https://x.com>**"),
            ("plain_text_unchanged", "Hello world", "Hello world"),
            # Mismatched openers/closers shouldn't be rewritten — leave alone so we
            # don't silently corrupt content that looks vaguely link-shaped.
            ("mismatched_markers_unchanged", "**<https://x.com*>", "**<https://x.com*>"),
        ]
    )
    def test_repair(self, _name, text, expected):
        assert _repair_link_trailing_markers(text) == expected


class TestWrapBareUrlsInEmphasis(unittest.TestCase):
    @parameterized.expand(
        [
            ("bold_bare_url", "**https://x.com**", "**<https://x.com>**"),
            ("italic_bare_url", "*https://x.com*", "*<https://x.com>*"),
            ("underscore_bare_url", "_https://x.com_", "_<https://x.com>_"),
            ("strike_bare_url", "~~https://x.com~~", "~~<https://x.com>~~"),
            (
                "url_with_path_and_query",
                "**https://github.com/PostHog/posthog.com/pull/17450?foo=bar**",
                "**<https://github.com/PostHog/posthog.com/pull/17450?foo=bar>**",
            ),
            (
                "two_bare_urls_in_one_line",
                "**https://a.com** and *https://b.com*",
                "**<https://a.com>** and *<https://b.com>*",
            ),
            # Surrounded by sentence text — only the wrapped URL should be touched.
            (
                "url_inside_sentence",
                "Draft PR opened: **https://x.com/pr/1**",
                "Draft PR opened: **<https://x.com/pr/1>**",
            ),
            # Already bracketed — leave alone so we don't double-wrap.
            ("autolink_already_bracketed", "**<https://x.com>**", "**<https://x.com>**"),
            # Standard markdown link — handled correctly by the converter as-is.
            ("markdown_link_in_bold_unchanged", "**[label](https://x.com)**", "**[label](https://x.com)**"),
            # Non-URL bold spans must not be rewritten.
            ("plain_bold_unchanged", "**hello world**", "**hello world**"),
            ("plain_text_unchanged", "Visit https://x.com without bolding", "Visit https://x.com without bolding"),
            # A bare URL not directly adjacent to the marker shouldn't be wrapped — the
            # surrounding text means the emphasis already flanks whitespace and Slack
            # renders it correctly without help.
            (
                "url_inside_bold_span_with_surrounding_text",
                "**check https://x.com later**",
                "**check https://x.com later**",
            ),
        ]
    )
    def test_wrap(self, _name, text, expected):
        assert _wrap_bare_urls_in_emphasis(text) == expected


class TestNeutralizeApproxTildes(unittest.TestCase):
    @parameterized.expand(
        [
            ("dollar", "~$36.0k", "∼$36.0k"),
            ("bare_number", "~5.1k/day", "∼5.1k/day"),
            ("time", "roughly ~2pm PT", "roughly ∼2pm PT"),
            ("percent", "up ~10% MoM", "up ∼10% MoM"),
            ("euro", "~€40", "∼€40"),
            ("multiple_on_one_line", "~$5k then ~$9k", "∼$5k then ∼$9k"),
            # A genuine ``~~strikethrough~~`` run must survive untouched — its tildes are
            # adjacent to each other, not to a quantity.
            ("strikethrough_run_preserved", "~~$5 off~~", "~~$5 off~~"),
            # A tilde glued to a preceding word is a git ref or range, not "approximately".
            ("git_ref_left_alone", "rebase onto HEAD~2", "rebase onto HEAD~2"),
            ("numeric_range_left_alone", "5~10 items", "5~10 items"),
            # Paths, standalone tildes, and non-quantity tildes are literal characters that
            # never form an accidental strikethrough, so they are left alone.
            ("path_left_alone", "see ~/notes/report.md", "see ~/notes/report.md"),
            ("tilde_before_letter_left_alone", "~foo", "~foo"),
            ("tilde_before_space_left_alone", "~ $5", "~ $5"),
            ("plain_text_unchanged", "no tildes here", "no tildes here"),
            # Code spans/fences hold literal content Slack never strikes through, so a tilde
            # there stays ASCII even when it looks like an approximation.
            ("inline_code_left_alone", "run `git reset HEAD~1` and `~$5`", "run `git reset HEAD~1` and `~$5`"),
            (
                "fenced_block_left_alone",
                "```\ninstall foo@~1.2.0\ncost ~$5\n```",
                "```\ninstall foo@~1.2.0\ncost ~$5\n```",
            ),
            ("approx_outside_code_still_converted", "about ~$5 for `~$9`", "about ∼$5 for `~$9`"),
        ]
    )
    def test_neutralize(self, _name, text, expected):
        assert _neutralize_approx_tildes(text) == expected


class TestAppendUnconfirmedAttachmentNotice(unittest.TestCase):
    def test_appends_notice_for_local_file_delivery_claim_without_artifacts(self):
        text = "Generated /tmp/workspace/report.pdf and it is attached."
        result = _append_unconfirmed_attachment_notice(text, artifacts=[], origin_product="slack")

        assert result.endswith("no file was attached to Slack for this run._")

    def test_skips_notice_for_negated_claim(self):
        text = "Generated /tmp/workspace/report.pdf, but it is not attached yet."
        result = _append_unconfirmed_attachment_notice(text, artifacts=[], origin_product="slack")

        assert result == text

    def test_skips_notice_for_non_slack_run(self):
        text = "Generated /tmp/workspace/report.pdf and it is attached."
        result = _append_unconfirmed_attachment_notice(text, artifacts=[], origin_product="user_created")

        assert result == text


class TestSplitTextForSlack(TestCase):
    def test_short_text_returns_single_chunk(self):
        assert _split_markdown_for_slack("hello world") == ["hello world"]

    def test_each_chunk_under_limit(self):
        paragraph = ("word " * 200).strip()
        text = "\n\n".join([paragraph] * 10)
        chunks = _split_markdown_for_slack(text)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= SLACK_MESSAGE_TEXT_LIMIT

    def test_split_prefers_paragraph_boundary(self):
        paragraph = ("alpha " * 400).strip()  # ~2400 chars per paragraph
        text = f"{paragraph}\n\n{paragraph}"
        chunks = _split_markdown_for_slack(text)
        assert len(chunks) == 2
        assert chunks[0] == paragraph
        assert chunks[1] == paragraph

    def test_split_falls_back_to_line_within_paragraph(self):
        line = ("alpha " * 100).strip()  # ~600 chars
        text = "\n".join([line] * 10)  # single paragraph, ~6000 chars
        chunks = _split_markdown_for_slack(text)
        assert len(chunks) >= 2
        for chunk in chunks:
            for chunk_line in chunk.split("\n"):
                assert chunk_line == line

    def test_hard_breaks_single_long_line(self):
        line = "x" * (SLACK_MESSAGE_TEXT_LIMIT + 500)
        chunks = _split_markdown_for_slack(line)
        assert len(chunks) == 2
        assert all(len(chunk) <= SLACK_MESSAGE_TEXT_LIMIT for chunk in chunks)
        assert "".join(chunks) == line

    def test_oversized_code_block_keeps_fences_balanced(self):
        body_lines = [f"line {i:04d}" for i in range(800)]
        body = "\n".join(body_lines)
        text = f"```python\n{body}\n```"
        chunks = _split_markdown_for_slack(text)
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
        chunks = _split_markdown_for_slack(text)
        joined = "\n\n".join(chunks)
        assert "```js\n" in joined
        assert joined.count("```") % 2 == 0

    def test_paragraph_split_preserves_markdown_for_per_chunk_conversion(self):
        # Each chunk must stay a valid markdown document on its own so that the
        # per-chunk mrkdwn conversion produces correctly-rendered output.
        paragraph_a = "This **bold** and [link](https://example.com) " * 50
        paragraph_b = "Another **bold** and [link](https://example.com) " * 50
        text = f"{paragraph_a.strip()}\n\n{paragraph_b.strip()}"
        chunks = _split_markdown_for_slack(text)
        assert len(chunks) == 2
        for chunk in chunks:
            converted = _markdown_to_slack_mrkdwn(chunk)
            assert "*bold*" in converted
            assert "<https://example.com|link>" in converted
            assert "**" not in converted  # inline bold markers must be fully converted

    def test_hard_char_break_leaves_broken_inline_span_as_literal(self):
        # A single line longer than the limit forces a hard char break. Doing it
        # before conversion means a halved ``**bold**`` simply fails to match the
        # converter regex on either side, so both chunks keep the literal ``**``
        # rather than ending up with a dangling unbalanced ``*`` in Slack mrkdwn.
        prefix = "x" * (SLACK_MESSAGE_TEXT_LIMIT - 4)
        line = prefix + "**bold**" + "y" * 100
        chunks = _split_markdown_for_slack(line)
        assert len(chunks) == 2
        converted_first = _markdown_to_slack_mrkdwn(chunks[0])
        converted_second = _markdown_to_slack_mrkdwn(chunks[1])
        # Neither chunk should contain a valid Slack-mrkdwn ``*bold*`` because
        # the span was halved; both should preserve the raw asterisks instead.
        assert "*bold*" not in converted_first
        assert "*bold*" not in converted_second
        # And, critically, no chunk leaks a lone unbalanced ``*`` that would
        # turn the rest of the message italic.
        for chunk in (converted_first, converted_second):
            assert chunk.count("*") % 2 == 0


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
