from django.test import TestCase

from parameterized import parameterized

from posthog.models import Comment, Organization, OrganizationMembership, Team, User
from posthog.models.scoping import team_scope

from products.canvas.backend.models import Canvas
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.models import Channel, Task, TaskActivity, TaskCommentActivity, TaskRun


class CommentActivityTestCase(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Growth Team")
        self.enterContext(team_scope(self.team.id, canonical=True))
        self.author = User.objects.create_user(email="author@example.com", first_name="Ann", password="password")
        self.peer = User.objects.create_user(email="peer@example.com", first_name="Bob", password="password")
        for user in (self.author, self.peer):
            self.organization.members.add(user)
            OrganizationMembership.objects.filter(user=user, organization=self.organization).update(
                level=OrganizationMembership.Level.ADMIN
            )
        self.channel = Channel.objects.unscoped().create(team=self.team, name="general", created_by=self.author)
        self.task = Task.objects.create(team=self.team, title="Ship it", created_by=self.author, channel=self.channel)
        self.task_run = TaskRun.objects.create(
            team=self.team,
            task=self.task,
            artifacts=[{"id": "artifact-1", "name": "report.md", "type": "output"}],
        )

    def _comment(self, *, scope: str = "task_artifact", item_id: str = "artifact-1", **kwargs) -> Comment:
        context = kwargs.pop("item_context", {"anchor": {"kind": "document"}, "taskId": str(self.task.id)})
        return Comment.objects.create(
            team=self.team,
            scope=scope,
            item_id=item_id,
            item_context=context,
            content=kwargs.pop("content", "this needs a guard"),
            created_by=kwargs.pop("created_by", self.peer),
            **kwargs,
        )

    def _record_activity(self, comment: Comment, user_ids: list[int] | None = None) -> None:
        tasks_facade.record_comment_activity(
            team_id=comment.team_id,
            comment_id=comment.id,
            mentioned_user_ids=user_ids or [],
        )


class TestCommentActivity(CommentActivityTestCase):
    def test_mention_on_an_artifact_comment_reaches_the_feed(self):
        comment = self._comment()

        self._record_activity(comment, [self.author.id])

        row = TaskCommentActivity.objects.get(team=self.team, user=self.author)
        assert row.task_id == self.task.id
        assert row.comment_id == comment.id
        assert row.read_at is None

    def test_task_scoped_comment_resolves_from_its_item_id(self):
        comment = self._comment(scope="task", item_id=str(self.task.id), item_context={"anchor": {"kind": "document"}})

        self._record_activity(comment, [self.author.id])

        assert TaskCommentActivity.objects.filter(team=self.team, user=self.author, task=self.task).exists()

    def test_canvas_comment_uses_its_generation_task(self):
        canvas = Canvas.objects.create(
            team=self.team,
            channel=self.channel,
            name="Launch canvas",
            created_by=self.peer,
            generation_task_id=self.task.id,
        )
        comment = self._comment(scope="desktop_canvas", item_id=str(canvas.id))

        self._record_activity(comment, [self.author.id])

        assert TaskCommentActivity.objects.filter(team=self.team, user=self.author, task=self.task).exists()

    def test_feed_renders_the_comment_author_and_text(self):
        comment = self._comment()
        self._record_activity(comment, [self.author.id])

        page = tasks_facade.list_task_activity(self.team.id, self.author.id)

        activity = next(row for row in page.results if row.latest_comment_id == comment.id)
        assert activity.snippet == "this needs a guard"
        assert activity.latest_author is not None
        assert activity.latest_author.id == self.peer.id
        assert activity.latest_comment_scope == "task_artifact"
        assert activity.latest_comment_item_id == "artifact-1"

    def test_feed_bounds_comment_snippets(self):
        comment = self._comment(content="a" * 2048)
        self._record_activity(comment, [self.author.id])

        activity = tasks_facade.list_task_activity(self.team.id, self.author.id).results[0]

        assert activity.snippet == "a" * 1024

    def test_distinct_comments_on_one_task_remain_distinct_activity_entries(self):
        first = self._comment(content="first request")
        second = self._comment(content="second request")

        self._record_activity(first, [self.author.id])
        self._record_activity(second, [self.author.id])

        mentions = [
            row
            for row in tasks_facade.list_task_activity(self.team.id, self.author.id).results
            if row.latest_comment_id
        ]
        assert [row.latest_comment_id for row in mentions] == [second.id, first.id]
        assert [row.snippet for row in mentions] == ["second request", "first request"]

    def test_reply_mention_links_activity_to_the_root_thread(self):
        root = self._comment(content="root")
        reply = self._comment(content="reply", source_comment=root)

        self._record_activity(reply, [self.author.id])

        activity = tasks_facade.list_task_activity(self.team.id, self.author.id).results[0]
        assert activity.latest_comment_id == root.id
        assert activity.latest_comment_scope == "task_artifact"
        assert activity.latest_comment_item_id == "artifact-1"

    def test_author_is_not_notified_of_their_own_mention(self):
        comment = self._comment(created_by=self.author)

        self._record_activity(comment, [self.author.id])

        assert not TaskCommentActivity.objects.filter(team=self.team, user=self.author).exists()

    def test_personal_channel_mentions_do_not_create_activity(self):
        self.channel.channel_type = Channel.ChannelType.PERSONAL
        self.channel.save(update_fields=["channel_type"])
        comment = self._comment()

        self._record_activity(comment, [self.author.id])

        assert not TaskCommentActivity.objects.filter(team=self.team, user=self.author).exists()

    def test_team_readable_personal_task_does_not_create_activity(self):
        self.channel.channel_type = Channel.ChannelType.PERSONAL
        self.channel.save(update_fields=["channel_type"])
        self.task.origin_product = Task.OriginProduct.EXPERIMENTS
        self.task.save(update_fields=["origin_product"])
        comment = self._comment()

        self._record_activity(comment, [self.author.id])

        assert not TaskCommentActivity.objects.filter(team=self.team, user=self.author).exists()

    def test_team_readable_channel_less_task_creates_activity(self):
        self.task.channel = None
        self.task.origin_product = Task.OriginProduct.EXPERIMENTS
        self.task.save(update_fields=["channel", "origin_product"])
        comment = self._comment()

        self._record_activity(comment)

        assert TaskCommentActivity.objects.filter(team=self.team, user=self.author).exists()

    def test_deleted_channel_mentions_do_not_create_activity(self):
        self.channel.deleted = True
        self.channel.save(update_fields=["deleted"])
        comment = self._comment()

        self._record_activity(comment, [self.author.id])

        assert not TaskCommentActivity.objects.filter(team=self.team, user=self.author).exists()

    def test_deleted_comments_are_hidden_from_activity(self):
        unread_before = tasks_facade.count_unread_task_activity(self.team.id, self.author.id)
        comment = self._comment()
        self._record_activity(comment, [self.author.id])
        comment.deleted = True
        comment.save(update_fields=["deleted"])

        page = tasks_facade.list_task_activity(self.team.id, self.author.id)

        assert not any(row.latest_comment_id == comment.id for row in page.results)
        assert page.unread_count == unread_before

    @parameterized.expand(
        [
            ("unknown_task", {"anchor": {"kind": "document"}, "taskId": "3f1d4b7e-0000-4000-8000-000000000000"}),
            ("missing_task_id", {"anchor": {"kind": "document"}}),
            ("malformed_task_id", {"anchor": {"kind": "document"}, "taskId": "not-a-uuid"}),
        ]
    )
    def test_unresolvable_task_records_nothing(self, _name: str, context: dict):
        comment = self._comment(item_context=context)

        self._record_activity(comment, [self.author.id])

        assert not TaskCommentActivity.objects.filter(team=self.team).exists()

    def test_comment_from_another_product_is_ignored(self):
        comment = self._comment(scope="Insight", item_id="42")

        self._record_activity(comment, [self.author.id])

        assert not TaskCommentActivity.objects.filter(team=self.team).exists()

    def test_top_level_comment_notifies_the_task_owner(self):
        comment = self._comment()

        self._record_activity(comment)

        row = TaskCommentActivity.objects.get(team=self.team, user=self.author)
        assert row.kind == TaskCommentActivity.Kind.OWNED_ITEM_COMMENT
        assert row.root_comment_id == comment.id

    def test_reply_notifies_root_and_previous_reply_authors(self):
        participant = User.objects.create_user(email="participant@example.com", first_name="Pat", password="password")
        self.organization.members.add(participant)
        root = self._comment(created_by=self.author, content="root")
        previous_reply = self._comment(created_by=participant, content="first reply", source_comment=root)
        self._record_activity(previous_reply)
        reply = self._comment(created_by=self.peer, content="second reply", source_comment=root)

        self._record_activity(reply)

        rows = TaskCommentActivity.objects.filter(comment=reply)
        assert set(rows.values_list("user_id", flat=True)) == {self.author.id, participant.id}
        assert set(rows.values_list("kind", flat=True)) == {TaskCommentActivity.Kind.THREAD_REPLY}

    def test_mention_overrides_thread_reply_without_creating_a_duplicate(self):
        root = self._comment(created_by=self.author, content="root")
        reply = self._comment(created_by=self.peer, content="reply", source_comment=root)

        self._record_activity(reply, [self.author.id])

        row = TaskCommentActivity.objects.get(comment=reply, user=self.author)
        assert row.kind == TaskCommentActivity.Kind.MENTION

    def test_mention_does_not_subscribe_a_non_participant_to_later_replies(self):
        mentioned = User.objects.create_user(email="mentioned@example.com", first_name="Mel", password="password")
        self.organization.members.add(mentioned)
        root = self._comment(created_by=self.author, content="root")
        first_reply = self._comment(created_by=self.peer, content="tag", source_comment=root)
        self._record_activity(first_reply, [mentioned.id])
        second_reply = self._comment(created_by=self.peer, content="later", source_comment=root)

        self._record_activity(second_reply)

        assert not TaskCommentActivity.objects.filter(comment=second_reply, user=mentioned).exists()

    def test_marking_one_comment_read_keeps_sibling_notifications_unread(self):
        first = self._comment(content="first")
        second = self._comment(content="second")
        self._record_activity(first)
        self._record_activity(second)
        first_activity = TaskCommentActivity.objects.get(comment=first, user=self.author)
        TaskActivity.record(
            team_id=self.team.id,
            user_id=self.author.id,
            task_id=self.task.id,
            kind=TaskActivity.Kind.AWAITING_INPUT,
            activity_at=first.created_at,
        )

        tasks_facade.mark_task_activity_read(
            self.team.id,
            self.author.id,
            [(self.task.id, first.created_at, first_activity.id)],
        )

        first_activity.refresh_from_db()
        assert first_activity.read_at is not None
        assert TaskCommentActivity.objects.get(comment=second, user=self.author).read_at is None
        assert TaskActivity.objects.get(team=self.team, user=self.author, task=self.task).read_at is None


class TestCommentActivityTimeline(CommentActivityTestCase):
    """The collapsed comment rows the activity timeline renders."""

    def _rows(self):
        page = tasks_facade.list_task_comment_activity(self.task.id, self.team.id, self.author.id)
        assert page is not None
        return page.comments

    def test_a_thread_is_one_row_positioned_at_its_newest_reply(self):
        # One row per reply would push every other event off the panel, so replies fold into
        # the root and the root moves to the newest reply's time.
        root = self._comment(content="this needs a guard")
        older = self._comment(content="unrelated thread")
        reply = self._comment(content="agreed, on it", source_comment=root, created_by=self.author)

        rows = self._rows()

        self.assertEqual([row.id for row in rows], [root.id, older.id])
        self.assertEqual(rows[0].reply_count, 1)
        self.assertEqual(rows[0].last_activity_at, reply.created_at)
        self.assertEqual(rows[0].latest_reply.content, "agreed, on it")

    def test_resolve_events_are_not_replies(self):
        # The Comments tab excludes thread-state events from its count; a second definition
        # here is how the two surfaces start disagreeing.
        root = self._comment()
        self._comment(content="agreed", source_comment=root, created_by=self.author)
        self._comment(
            content="Resolved this thread",
            source_comment=root,
            created_by=self.author,
            item_context={"taskId": str(self.task.id), "threadState": "resolved"},
        )

        row = self._rows()[0]

        self.assertEqual(row.reply_count, 1)
        self.assertTrue(row.resolved)
        assert row.state_event is not None
        self.assertEqual(row.state_event.state, "resolved")
        self.assertEqual(row.state_event.author.id, self.author.id)

    def test_reopening_supersedes_an_earlier_resolve(self):
        root = self._comment()
        for state in ("resolved", "open"):
            self._comment(
                content=f"{state} this thread",
                source_comment=root,
                created_by=self.author,
                item_context={"taskId": str(self.task.id), "threadState": state},
            )

        row = self._rows()[0]

        self.assertFalse(row.resolved)
        assert row.state_event is not None
        self.assertEqual(row.state_event.state, "open")

    def test_participants_are_listed_in_speaking_order(self):
        root = self._comment(created_by=self.peer)
        self._comment(content="looking", source_comment=root, created_by=self.author)
        self._comment(content="still looking", source_comment=root, created_by=self.author)

        row = self._rows()[0]

        self.assertEqual([person.id for person in row.participants], [self.peer.id, self.author.id])

    def test_mentions_come_from_the_projected_notification_rows(self):
        root = self._comment()
        self._record_activity(root, [self.author.id])

        self.assertEqual(self._rows()[0].mentioned_user_ids, [self.author.id])

    def test_the_anchor_travels_with_the_row(self):
        # A comment without its quoted selection is just a notification.
        self._comment(
            item_context={
                "taskId": str(self.task.id),
                "anchor": {"kind": "text", "quote": "every event should also go to the activity panel"},
            }
        )

        self.assertEqual(self._rows()[0].selected_text, "every event should also go to the activity panel")

    def test_threads_from_every_target_arrive_in_one_call(self):
        canvas = Canvas.objects.create(
            team=self.team,
            channel=self.channel,
            name="Activity mockup",
            created_by=self.author,
            generation_task_id=self.task.id,
        )
        self._comment(scope="task", item_id=str(self.task.id), item_context={"taskId": str(self.task.id)})
        self._comment(scope="desktop_canvas", item_id=str(canvas.id))
        self._comment()

        self.assertEqual({row.target.type for row in self._rows()}, {"task", "canvas", "artifact"})

    def test_a_task_the_user_cannot_see_returns_nothing(self):
        # A task in another team is invisible here, so the endpoint must not answer for it.
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        with team_scope(other_team.id, canonical=True):
            stranger_task = Task.objects.create(team=other_team, title="Not yours", created_by=self.peer)

        self.assertIsNone(tasks_facade.list_task_comment_activity(stranger_task.id, self.team.id, self.author.id))
