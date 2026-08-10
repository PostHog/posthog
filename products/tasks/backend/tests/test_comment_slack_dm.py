from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models import Comment, OrganizationMembership, User
from posthog.models.integration import Integration
from posthog.models.user_integration import UserIntegration

from products.tasks.backend.models import TaskCommentActivity
from products.tasks.backend.tests.test_comment_activity import CommentActivityTestCase

SLACK_WORKSPACE_ID = "T123"


class TestCommentSlackDm(CommentActivityTestCase):
    def setUp(self) -> None:
        super().setUp()
        Integration.objects.create(
            team=self.team, kind="slack", integration_id=SLACK_WORKSPACE_ID, config={"scope": "chat:write"}
        )
        self._link_slack(self.author, "U-author")
        self._opt_in(self.author)

        flag_patch = patch(
            "products.tasks.backend.logic.services.comment_slack_dm.is_slack_app_oauth_enabled", return_value=True
        )
        client_patch = patch("products.tasks.backend.logic.services.comment_slack_dm.SlackIntegration")
        self.addCleanup(flag_patch.stop)
        self.addCleanup(client_patch.stop)
        flag_patch.start()
        self.slack_client = MagicMock()
        client_patch.start().return_value.client = self.slack_client

    def _link_slack(self, user, slack_user_id: str) -> None:
        UserIntegration.objects.create(
            user=user,
            kind=UserIntegration.IntegrationKind.SLACK,
            integration_id=slack_user_id,
            config={"slack_team_id": SLACK_WORKSPACE_ID},
        )

    def _opt_in(self, user, enabled: bool = True) -> None:
        user.partial_notification_settings = {"code_comments_slack_dm": enabled}
        user.save()

    def _record_activity(self, comment: Comment, user_ids: list[int] | None = None) -> None:
        # Delivery is enqueued on commit, which a TestCase never reaches on its own.
        with self.captureOnCommitCallbacks(execute=True):
            super()._record_activity(comment, user_ids)

    def _dm_channels(self) -> list[str]:
        return [call.kwargs["channel"] for call in self.slack_client.chat_postMessage.call_args_list]

    def test_mention_dms_the_mentioned_user(self):
        comment = self._comment()

        self._record_activity(comment, [self.author.id])

        assert self._dm_channels() == ["U-author"]
        text = self.slack_client.chat_postMessage.call_args.kwargs["blocks"][0]["text"]["text"]
        assert "mentioned you" in text
        assert "this needs a guard" in text

    def test_no_dm_when_the_user_opted_out(self):
        self._opt_in(self.author, False)

        self._record_activity(self._comment(), [self.author.id])

        assert self._dm_channels() == []

    @parameterized.expand(
        [
            # Same workspace as the integration: the directory match is trustworthy.
            ("same_workspace", SLACK_WORKSPACE_ID, ["U-by-email"]),
            # A Slack Connect guest whose profile email its own admin controls.
            ("external_workspace", "T-OTHER", []),
        ]
    )
    def test_unlinked_user_is_matched_by_email_only_inside_the_workspace(
        self, _name: str, profile_team_id: str, expected: list[str]
    ):
        UserIntegration.objects.filter(user=self.author).delete()

        with (
            patch(
                "products.tasks.backend.logic.services.comment_slack_dm.lookup_slack_user_id_by_email",
                return_value="U-by-email",
            ),
            patch(
                "products.tasks.backend.logic.services.comment_slack_dm.resolve_slack_user",
                return_value={"name": "Ann", "team_id": profile_team_id},
            ),
        ):
            self._record_activity(self._comment(), [self.author.id])

        assert self._dm_channels() == expected

    def test_the_linked_account_wins_over_an_email_match(self):
        with patch(
            "products.tasks.backend.logic.services.comment_slack_dm.lookup_slack_user_id_by_email",
            return_value="U-by-email",
        ) as lookup:
            self._record_activity(self._comment(), [self.author.id])

        assert self._dm_channels() == ["U-author"]
        lookup.assert_not_called()

    @parameterized.expand(
        [
            ("reaction", {"is_emoji": True}),
            ("resolve", {"threadState": "resolved"}),
        ]
    )
    def test_reactions_and_thread_state_changes_do_not_dm(self, _name: str, extra_context: dict):
        root = self._comment(created_by=self.author)
        reply = self._comment(
            created_by=self.peer,
            source_comment=root,
            item_context={"anchor": {"kind": "document"}, "taskId": str(self.task.id), **extra_context},
        )

        self._record_activity(reply)

        assert self._dm_channels() == []

    def test_reply_dms_the_thread_author_only(self):
        third = User.objects.create_user(email="carol@example.com", first_name="Carol", password="password")
        self.organization.members.add(third)
        OrganizationMembership.objects.filter(user=third, organization=self.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )
        self._link_slack(third, "U-carol")
        self._opt_in(third)
        root = self._comment(created_by=self.author)
        Comment.objects.create(
            team=self.team,
            scope=root.scope,
            item_id=root.item_id,
            item_context=root.item_context,
            source_comment=root,
            content="chiming in",
            created_by=third,
        )
        latest_reply = self._comment(created_by=self.peer, source_comment=root, content="on it")

        self._record_activity(latest_reply)

        assert self._dm_channels() == ["U-author"]

    def test_slack_failure_does_not_break_activity_projection(self):
        self.slack_client.chat_postMessage.side_effect = Exception("slack down")
        comment = self._comment()

        self._record_activity(comment, [self.author.id])

        assert TaskCommentActivity.objects.filter(team=self.team, user=self.author, comment=comment).exists()
