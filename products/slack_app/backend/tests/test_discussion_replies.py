from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.models.comment import Comment, CommentSlackThread
from posthog.models.integration import Integration

from products.slack_app.backend.discussion_replies import try_ingest_discussion_reply

# The Slack profile lookup happens inside the ingest Celery task (eager in tests).
RESOLVE = "posthog.tasks.comment_slack_sync.resolve_slack_user"

PERMALINK = "https://acme.slack.com/files/U1/F1/screenshot.png"


class TestIngestDiscussionReply(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id="T1", sensitive_config={"access_token": "t"}
        )
        self.root = Comment.objects.create(team=self.team, scope="Insight", item_id="42", content="root")
        CommentSlackThread.objects.for_team(self.team.id).create(
            team=self.team,
            scope="Insight",
            item_id="42",
            source_comment=self.root,
            integration=self.integration,
            slack_channel_id="C1",
            slack_thread_ts="100.1",
        )

    def _event(self, **kwargs) -> dict:
        event = {
            "type": "message",
            "user": "U1",
            "channel": "C1",
            "thread_ts": "100.1",
            "ts": "100.2",
            "text": "hi from slack",
        }
        event.update(kwargs)
        return event

    def _ingest(self, event: dict) -> bool:
        return try_ingest_discussion_reply(event, [self.integration], event["channel"], event.get("thread_ts"), "T1")

    @patch(
        RESOLVE,
        return_value={"name": "Stranger", "email": "stranger@example.com", "avatar": "http://a", "team_id": "T_EXT"},
    )
    def test_ingests_reply_anchored_on_thread_root(self, _resolve):
        handled = self._ingest(self._event())

        assert handled is True
        reply = Comment.objects.get(source_comment=self.root)
        assert reply.item_context is not None
        assert reply.content == "hi from slack"
        assert (reply.scope, reply.item_id) == ("Insight", "42")
        assert reply.created_by_id is None  # stranger isn't an org member
        assert reply.item_context["from_slack"] is True
        assert reply.item_context["slack_author_name"] == "Stranger"
        # External participants' email / Slack user id must not leak through the comments API.
        assert "slack_author_email" not in reply.item_context
        assert "slack_user_id" not in reply.item_context

    @patch(RESOLVE)
    def test_maps_workspace_member_to_posthog_account_by_email(self, mock_resolve):
        mock_resolve.return_value = {"name": "Member", "email": self.user.email, "avatar": None, "team_id": "T1"}

        self._ingest(self._event())

        reply = Comment.objects.get(source_comment=self.root)
        assert reply.created_by_id == self.user.id

    @patch(RESOLVE)
    def test_external_workspace_author_is_never_attributed(self, mock_resolve):
        # Slack Connect: the author's profile email matches an org member, but they belong to a
        # different workspace whose admin controls that email — attributing would allow
        # impersonation, so the comment stays author-less.
        mock_resolve.return_value = {"name": "Imposter", "email": self.user.email, "avatar": None, "team_id": "T_EXT"}

        self._ingest(self._event())

        reply = Comment.objects.get(source_comment=self.root)
        assert reply.item_context is not None
        assert reply.created_by_id is None
        assert reply.item_context["slack_author_name"] == "Imposter"

    @patch(RESOLVE, return_value={"name": "X", "email": None, "avatar": None, "team_id": "T1"})
    def test_image_markdown_neutralized_in_content_and_rich_content(self, _resolve):
        # The discussion UI renders rich_content (preferred) or content as markdown without
        # disabling images — inbound Slack text must never carry live image syntax.
        payload = "look ![x](https://attacker.example/pixel)"
        blocks = [
            {
                "type": "rich_text",
                "elements": [{"type": "rich_text_section", "elements": [{"type": "text", "text": payload}]}],
            }
        ]
        self._ingest(self._event(text=payload, blocks=blocks))

        reply = Comment.objects.get(source_comment=self.root)
        assert reply.rich_content is not None
        assert "![" not in (reply.content or "")
        text_node = reply.rich_content["content"][0]["content"][0]["text"]
        assert text_node == "look !\\[x](https://attacker.example/pixel)"

    @patch(RESOLVE, return_value={"name": "X", "email": None, "avatar": None, "team_id": "T1"})
    def test_duplicate_event_delivery_creates_one_comment(self, _resolve):
        # Slack delivers at-least-once; the message ts is the idempotency key.
        assert self._ingest(self._event()) is True
        assert self._ingest(self._event()) is True

        assert Comment.objects.filter(source_comment=self.root).count() == 1

    def test_returns_false_for_unmirrored_thread(self):
        handled = self._ingest(self._event(thread_ts="999.9"))

        assert handled is False
        assert not Comment.objects.filter(source_comment=self.root).exists()

    @patch("products.slack_app.backend.discussion_replies.SlackThreadTaskMapping")
    def test_agent_task_thread_takes_precedence(self, mock_mapping):
        # A mirrored thread where someone also @-mentioned the coding agent: followups belong
        # to the agent pipeline, not the discussion.
        mock_mapping.objects.filter.return_value.exists.return_value = True

        handled = self._ingest(self._event())

        assert handled is False
        assert not Comment.objects.filter(source_comment=self.root).exists()

    @patch(RESOLVE, return_value={"name": "X", "email": None, "avatar": None, "team_id": "T1"})
    def test_empty_message_handled_without_creating_comment(self, _resolve):
        handled = self._ingest(self._event(text="", blocks=None))

        assert handled is True
        assert not Comment.objects.filter(source_comment=self.root).exists()

    @patch(RESOLVE, return_value={"name": "X", "email": None, "avatar": None, "team_id": "T1"})
    def test_caption_less_upload_creates_comment_with_placeholder(self, _resolve):
        # A file-only upload has no text and no blocks; without placeholders it produced no
        # comment at all, so the PostHog side never learned anything had been sent.
        event = self._event(
            text="",
            blocks=None,
            subtype="file_share",
            files=[{"id": "F1", "name": "screenshot.png", "mimetype": "image/png", "permalink": PERMALINK}],
        )

        assert self._ingest(event) is True

        reply = Comment.objects.get(source_comment=self.root)
        assert reply.content == f"📎 [screenshot.png]({PERMALINK})"

    @patch(RESOLVE, return_value={"name": "X", "email": None, "avatar": None, "team_id": "T1"})
    def test_caption_and_placeholder_both_land_in_content_and_rich_content(self, _resolve):
        # An upload with a caption arrives with blocks, so rich_content is set — and the UI
        # prefers it, meaning a placeholder added only to content would never be seen.
        blocks = [
            {
                "type": "rich_text",
                "elements": [{"type": "rich_text_section", "elements": [{"type": "text", "text": "here's the bug"}]}],
            }
        ]
        event = self._event(
            text="here's the bug",
            blocks=blocks,
            subtype="file_share",
            files=[{"id": "F1", "name": "screenshot.png", "permalink": PERMALINK}],
        )

        self._ingest(event)

        reply = Comment.objects.get(source_comment=self.root)
        assert reply.content is not None
        assert "here's the bug" in reply.content
        assert f"📎 [screenshot.png]({PERMALINK})" in reply.content
        assert reply.rich_content is not None
        rendered = [
            node["content"][0]["text"] for node in reply.rich_content["content"] if node.get("type") == "paragraph"
        ]
        assert rendered == ["here's the bug", f"📎 [screenshot.png]({PERMALINK})"]

    @patch(RESOLVE, return_value={"name": "X", "email": None, "avatar": None, "team_id": "T1"})
    def test_hostile_filename_cannot_break_out_of_placeholder_link(self, _resolve):
        # Anyone in an externally-shared channel can name a file whatever they like.
        event = self._event(
            text="",
            blocks=None,
            files=[{"id": "F1", "name": "![x](https://attacker.example/pixel).png", "permalink": PERMALINK}],
        )

        self._ingest(event)

        reply = Comment.objects.get(source_comment=self.root)
        assert reply.content is not None
        assert "![" not in reply.content
        assert "attacker.example" not in reply.content.split("](")[-1]
        assert reply.content.endswith(f"]({PERMALINK})")

    @patch(RESOLVE, return_value={"name": "X", "email": None, "avatar": None, "team_id": "T1"})
    def test_non_slack_permalink_degrades_to_unlinked_placeholder(self, _resolve):
        # A permalink is only trusted to the extent it points at Slack; the attachment still
        # gets a marker, just not a link to somewhere arbitrary.
        event = self._event(
            text="",
            blocks=None,
            files=[{"id": "F1", "name": "notes.pdf", "permalink": "https://attacker.example/steal"}],
        )

        self._ingest(event)

        reply = Comment.objects.get(source_comment=self.root)
        assert reply.content == "📎 notes.pdf"

    @patch(RESOLVE, return_value={"name": "X", "email": None, "avatar": None, "team_id": "T1"})
    def test_newline_in_filename_cannot_escape_the_link_text(self, _resolve):
        # A blank line inside the name ends the paragraph holding the link, and the bare URL
        # left behind renders as its own autolink.
        event = self._event(
            text="",
            blocks=None,
            files=[{"id": "F1", "name": "x\n\nhttps://attacker.example/phish", "permalink": PERMALINK}],
        )

        self._ingest(event)

        reply = Comment.objects.get(source_comment=self.root)
        assert reply.content == f"📎 [x https://attacker.example/phish]({PERMALINK})"

    @patch(RESOLVE, return_value={"name": "X", "email": None, "avatar": None, "team_id": "T1"})
    def test_backslash_permalink_is_not_trusted(self, _resolve):
        # urlparse reads the host as x.slack.com, but the WHATWG parser browsers use reads the
        # backslash as a path separator and lands on evil.example.
        event = self._event(
            text="",
            blocks=None,
            files=[{"id": "F1", "name": "a.png", "permalink": "https://evil.example\\path@x.slack.com/"}],
        )

        self._ingest(event)

        reply = Comment.objects.get(source_comment=self.root)
        assert reply.content == "📎 a.png"

    @patch(RESOLVE, return_value={"name": "X", "email": None, "avatar": None, "team_id": "T1"})
    def test_file_without_name_still_gets_a_marker(self, _resolve):
        self._ingest(self._event(text="", blocks=None, files=[{"id": "F1"}]))

        reply = Comment.objects.get(source_comment=self.root)
        assert reply.content == "📎 Attachment"

    @patch("posthog.tasks.comment_slack_sync.posthoganalytics.feature_enabled", return_value=False)
    @patch(RESOLVE, return_value={"name": "X", "email": None, "avatar": None, "team_id": "T1"})
    def test_kill_switch_stops_ingestion(self, _resolve, _flag):
        # Turning the flag explicitly off halts inbound sync on existing mirrors too.
        handled = self._ingest(self._event())

        assert handled is True  # still claimed as a discussion thread — just not written
        assert not Comment.objects.filter(source_comment=self.root).exists()
