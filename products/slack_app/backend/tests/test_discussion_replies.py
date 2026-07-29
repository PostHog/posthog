from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.models.comment import Comment, CommentSlackThread
from posthog.models.integration import Integration

from products.slack_app.backend.discussion_replies import try_ingest_discussion_reply

RESOLVE = "products.slack_app.backend.discussion_replies.resolve_slack_user"


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

    @patch(RESOLVE, return_value={"name": "Stranger", "email": "stranger@example.com", "avatar": "http://a"})
    def test_ingests_reply_anchored_on_thread_root(self, _resolve):
        handled = self._ingest(self._event())

        assert handled is True
        reply = Comment.objects.get(source_comment=self.root)
        assert reply.content == "hi from slack"
        assert (reply.scope, reply.item_id) == ("Insight", "42")
        assert reply.created_by_id is None  # stranger isn't an org member
        assert reply.item_context["from_slack"] is True
        assert reply.item_context["slack_author_name"] == "Stranger"

    @patch(RESOLVE)
    def test_maps_slack_user_to_posthog_account_by_email(self, mock_resolve):
        mock_resolve.return_value = {"name": "Member", "email": self.user.email, "avatar": None}

        self._ingest(self._event())

        reply = Comment.objects.get(source_comment=self.root)
        assert reply.created_by_id == self.user.id

    def test_returns_false_for_unmirrored_thread(self):
        handled = self._ingest(self._event(thread_ts="999.9"))

        assert handled is False
        assert not Comment.objects.filter(source_comment=self.root).exists()

    @patch(RESOLVE, return_value={"name": "X", "email": None, "avatar": None})
    def test_empty_message_handled_without_creating_comment(self, _resolve):
        handled = self._ingest(self._event(text="", blocks=None))

        assert handled is True
        assert not Comment.objects.filter(source_comment=self.root).exists()
