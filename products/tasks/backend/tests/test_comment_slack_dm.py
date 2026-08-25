from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import Comment, OrganizationMembership, User
from posthog.models.integration import Integration, SlackIntegration
from posthog.models.user_integration import UserIntegration

from products.access_control.backend.models.access_control import AccessControl
from products.canvas.backend.models import Canvas
from products.tasks.backend.logic.services.comment_slack_dm import send_comment_slack_dms
from products.tasks.backend.models import Channel, TaskCommentActivity
from products.tasks.backend.tests.test_comment_activity import CommentActivityTestCase

SLACK_WORKSPACE_ID = "T123"


class TestCommentSlackDm(CommentActivityTestCase):
    def setUp(self) -> None:
        super().setUp()
        Integration.objects.create(
            team=self.team, kind="slack", integration_id=SLACK_WORKSPACE_ID, config={"scope": "chat:write"}
        )
        self._link_slack(self.author, "U-author")

        flag_patch = patch(
            "products.tasks.backend.logic.services.comment_slack_dm.is_slack_app_oauth_enabled", return_value=True
        )
        client_patch = patch("products.tasks.backend.logic.services.comment_slack_dm.SlackIntegration")
        self.addCleanup(flag_patch.stop)
        self.addCleanup(client_patch.stop)
        flag_patch.start()
        self.slack_client = MagicMock()
        client_patch.start().return_value.client = self.slack_client

    def _link_slack(self, user, slack_user_id: str, workspace_id: str = SLACK_WORKSPACE_ID) -> None:
        UserIntegration.objects.create(
            user=user,
            kind=UserIntegration.IntegrationKind.SLACK,
            integration_id=slack_user_id,
            config={"slack_team_id": workspace_id},
        )

    def _opt_in(self, user, enabled: bool = True) -> None:
        user.partial_notification_settings = {"task_comments_slack_dm": enabled}
        user.save()

    def _record_activity(self, comment: Comment, user_ids: list[int] | None = None) -> None:
        # Delivery is enqueued on commit, which a TestCase never reaches on its own.
        with self.captureOnCommitCallbacks(execute=True):
            super()._record_activity(comment, user_ids)

    def _dm_heading(self) -> str:
        return self.slack_client.chat_postMessage.call_args.kwargs["text"]

    def _dm_body(self) -> str:
        attachment = self.slack_client.chat_postMessage.call_args.kwargs["attachments"][0]
        return attachment["blocks"][0]["text"]["text"]

    def _dm_channels(self) -> list[str]:
        return [call.kwargs["channel"] for call in self.slack_client.chat_postMessage.call_args_list]

    def test_mention_dms_the_mentioned_user_by_default(self):
        comment = self._comment()

        self._record_activity(comment, [self.author.id])

        assert self._dm_channels() == ["U-author"]
        assert "mentioned you" in self._dm_heading()
        body = self._dm_body()
        assert "this needs a guard" in body
        assert "mentioned you" not in body

    def test_an_overlong_comment_is_not_cut_inside_a_link(self):
        filler = "x" * 790
        comment = self._comment(content=f"{filler} see [the docs](https://posthog.com/docs/reference)")

        self._record_activity(comment, [self.author.id])

        body = self._dm_body()
        assert body.endswith("…")
        assert body.rfind("<") <= body.rfind(">")

    def test_inline_mention_lookups_are_bounded(self) -> None:
        third = User.objects.create_user(email="third@example.com", first_name="Carol", password="password")
        self.organization.members.add(third)
        emails = [self.author.email, self.peer.email, third.email]
        comment = self._comment(content=" ".join(f"@[Member {index}]({email})" for index, email in enumerate(emails)))

        with (
            patch("products.tasks.backend.logic.services.comment_slack_dm._MAX_MENTION_LOOKUPS_PER_SLACK_WORKSPACE", 2),
            patch(
                "products.tasks.backend.logic.services.comment_slack_dm.lookup_slack_user_id_by_email",
                side_effect=["U-one", "U-two"],
            ) as lookup,
            patch(
                "products.tasks.backend.logic.services.comment_slack_dm.resolve_slack_user",
                return_value={"team_id": SLACK_WORKSPACE_ID},
            ),
        ):
            self._record_activity(comment, [self.author.id])

        assert lookup.call_count == 2
        assert "<@U-one> <@U-two> @Member 2" in self._dm_body()

    def test_inline_mentions_only_query_slack_for_current_organization_members(self) -> None:
        comment = self._comment(content="@[Member](author@example.com) and @[Outsider](outsider@example.com)")

        with (
            patch(
                "products.tasks.backend.logic.services.comment_slack_dm.lookup_slack_user_id_by_email",
                return_value="U-member",
            ) as lookup,
            patch(
                "products.tasks.backend.logic.services.comment_slack_dm.resolve_slack_user",
                return_value={"team_id": SLACK_WORKSPACE_ID},
            ),
        ):
            self._record_activity(comment, [self.author.id])

        lookup.assert_called_once()
        assert lookup.call_args.args[2] == "author@example.com"
        assert "<@U-member> and @Outsider" in self._dm_body()

    def test_heading_escapes_user_controlled_slack_markup(self):
        self.peer.first_name = "<@U-ATTACKER>"
        self.peer.last_name = ""
        self.peer.save(update_fields=["first_name", "last_name"])
        self.task.title = "<https://example.com|click me>"
        self.task.save(update_fields=["title"])

        self._record_activity(self._comment(), [self.author.id])

        heading = self._dm_heading()
        assert "<@U-ATTACKER>" not in heading
        assert "*&lt;@U-ATTACKER&gt;* mentioned you on " in heading
        assert heading.endswith("|&lt;https://example.com-click me&gt;>")

    def test_no_dm_when_the_user_opted_out(self):
        self._opt_in(self.author, False)

        self._record_activity(self._comment(), [self.author.id])

        assert self._dm_channels() == []

    def test_deleted_comment_is_not_sent_after_delivery_is_enqueued(self):
        comment = self._comment()
        comment.deleted = True
        comment.save(update_fields=["deleted"])

        send_comment_slack_dms(
            team_id=self.team.id,
            comment_id=comment.id,
            task_id=self.task.id,
            recipients={self.author.id: TaskCommentActivity.Kind.MENTION},
        )

        assert self._dm_channels() == []

    def test_removed_organization_member_does_not_receive_a_dm(self):
        OrganizationMembership.objects.filter(user=self.author, organization=self.organization).delete()

        self._record_activity(self._comment(), [self.author.id])

        assert self._dm_channels() == []

    def test_inactive_user_does_not_receive_a_dm(self):
        self.author.is_active = False
        self.author.save(update_fields=["is_active"])
        comment = self._comment()

        send_comment_slack_dms(
            team_id=self.team.id,
            comment_id=comment.id,
            task_id=self.task.id,
            recipients={self.author.id: TaskCommentActivity.Kind.MENTION},
        )

        assert self._dm_channels() == []

    def test_project_member_without_access_does_not_receive_a_dm(self):
        self.organization.available_product_features = [
            {"name": AvailableFeature.ACCESS_CONTROL, "key": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        OrganizationMembership.objects.filter(user=self.author, organization=self.organization).update(
            level=OrganizationMembership.Level.MEMBER
        )
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            access_level="none",
        )

        self._record_activity(self._comment(), [self.author.id])

        assert self._dm_channels() == []

    def test_canvas_comment_dms_a_recipient_who_can_access_its_task(self):
        canvas = Canvas.objects.create(
            team=self.team,
            channel=self.channel,
            name="Launch canvas",
            created_by=self.peer,
            generation_task_id=self.task.id,
        )
        comment = self._comment(scope="desktop_canvas", item_id=str(canvas.id))

        self._record_activity(comment, [self.author.id])

        assert self._dm_channels() == ["U-author"]
        assert (
            f"/code/task/{self.task.id}?comment={comment.id}&scope=desktop_canvas&item={canvas.id}"
            in self._dm_heading()
        )

    def test_dm_links_to_the_desktop_task_bridge_anchored_on_the_comment(self):
        comment = self._comment()

        self._record_activity(comment, [self.author.id])

        assert f"/code/task/{self.task.id}?comment={comment.id}" in self._dm_heading()

    def test_canvas_comment_does_not_dm_a_recipient_without_canvas_access(self):
        personal_channel = Channel.objects.unscoped().create(
            team=self.team,
            name="private",
            channel_type=Channel.ChannelType.PERSONAL,
            created_by=self.peer,
        )
        canvas = Canvas.objects.create(
            team=self.team,
            channel=personal_channel,
            name="Launch canvas",
            created_by=self.peer,
            generation_task_id=self.task.id,
        )
        comment = self._comment(scope="desktop_canvas", item_id=str(canvas.id))

        self._record_activity(comment, [self.author.id])

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

    @parameterized.expand(
        [
            ("one_workspace", frozenset({SLACK_WORKSPACE_ID}), [f"U-{SLACK_WORKSPACE_ID}"]),
            ("multiple_workspaces", frozenset({SLACK_WORKSPACE_ID, "T456"}), []),
        ]
    )
    def test_unlinked_user_is_dmed_only_when_email_resolves_in_one_workspace(
        self, _name: str, matching_workspaces: frozenset[str], expected: list[str]
    ) -> None:
        second_workspace = "T456"
        Integration.objects.create(
            team=self.team, kind="slack", integration_id=second_workspace, config={"scope": "chat:write"}
        )
        UserIntegration.objects.filter(user=self.author).delete()

        def lookup_by_email(_slack: SlackIntegration, integration: Integration, _email: str) -> str | None:
            return f"U-{integration.integration_id}" if integration.integration_id in matching_workspaces else None

        with (
            patch(
                "products.tasks.backend.logic.services.comment_slack_dm.lookup_slack_user_id_by_email",
                side_effect=lookup_by_email,
            ),
            patch(
                "products.tasks.backend.logic.services.comment_slack_dm.resolve_slack_user",
                side_effect=lambda _client, _user_id, *, workspace: {"team_id": workspace},
            ),
        ):
            self._record_activity(self._comment())

        assert self._dm_channels() == expected
        if expected:
            assert "commented on" in self._dm_heading()

    def test_the_linked_account_wins_over_an_email_match(self):
        with patch(
            "products.tasks.backend.logic.services.comment_slack_dm.lookup_slack_user_id_by_email",
            return_value="U-by-email",
        ) as lookup:
            self._record_activity(self._comment(), [self.author.id])

        assert self._dm_channels() == ["U-author"]
        lookup.assert_not_called()

    def test_linked_workspace_selects_the_matching_slack_integration(self):
        second_workspace = "T456"
        Integration.objects.create(
            team=self.team, kind="slack", integration_id=second_workspace, config={"scope": "chat:write"}
        )
        self._link_slack(self.author, "U-author-second-workspace", second_workspace)

        self._record_activity(self._comment(), [self.author.id])

        assert self._dm_channels() == ["U-author-second-workspace"]

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

    def test_a_slack_failure_for_one_recipient_does_not_skip_the_next_recipient(self):
        third = User.objects.create_user(email="carol@example.com", first_name="Carol", password="password")
        self.organization.members.add(third)
        self._link_slack(third, "U-carol")
        self._opt_in(third)
        self.slack_client.chat_postMessage.side_effect = [Exception("slack down"), None]

        self._record_activity(self._comment(), [self.author.id, third.id])

        assert self._dm_channels() == ["U-author", "U-carol"]
