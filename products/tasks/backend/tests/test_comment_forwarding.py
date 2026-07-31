from unittest.mock import patch

from django.test import TestCase

from parameterized import parameterized

from posthog.models import Comment, Organization, OrganizationMembership, Team, User

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.models import Task, TaskActivity, TaskCommentForward, TaskRun


class CommentForwardingTestCase(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Growth Team")
        self.author = User.objects.create_user(email="author@example.com", first_name="Ann", password="password")
        self.peer = User.objects.create_user(email="peer@example.com", first_name="Bob", password="password")
        for user in (self.author, self.peer):
            self.organization.members.add(user)
            OrganizationMembership.objects.filter(user=user, organization=self.organization).update(
                level=OrganizationMembership.Level.ADMIN
            )
        self.task = Task.objects.create(team=self.team, title="Ship it", created_by=self.author)

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

    def _record_mentions(self, comment: Comment, user_ids: list[int]) -> None:
        tasks_facade.record_comment_mention_activity(
            team_id=comment.team_id,
            scope=comment.scope,
            item_id=comment.item_id,
            item_context=comment.item_context,
            comment_id=comment.id,
            author_id=comment.created_by_id,
            created_at=comment.created_at,
            mentioned_user_ids=user_ids,
        )


class TestCommentMentionActivity(CommentForwardingTestCase):
    def test_mention_on_an_artifact_comment_reaches_the_feed(self):
        comment = self._comment()

        self._record_mentions(comment, [self.author.id])

        row = TaskActivity.objects.get(team=self.team, user=self.author)
        assert row.task_id == self.task.id
        assert row.kind == TaskActivity.Kind.MENTION
        assert row.comment_id == comment.id
        assert row.read_at is None

    # A task-scoped comment names its task in item_id, so it needs no client-supplied hint.
    def test_task_scoped_comment_resolves_from_its_item_id(self):
        comment = self._comment(scope="task", item_id=str(self.task.id), item_context={"anchor": {"kind": "document"}})

        self._record_mentions(comment, [self.author.id])

        assert TaskActivity.objects.filter(team=self.team, user=self.author, task=self.task).exists()

    def test_feed_renders_the_comment_author_and_text(self):
        comment = self._comment()
        self._record_mentions(comment, [self.author.id])

        page = tasks_facade.list_task_activity(self.team.id, self.author.id)

        assert len(page.results) == 1
        assert page.results[0].snippet == "this needs a guard"
        assert page.results[0].latest_author is not None
        assert page.results[0].latest_author.id == self.peer.id

    def test_author_is_not_notified_of_their_own_mention(self):
        comment = self._comment(created_by=self.author)

        self._record_mentions(comment, [self.author.id])

        assert not TaskActivity.objects.filter(team=self.team, user=self.author).exists()

    # The task id rides in on the request for resource-scoped comments, so a caller must not
    # be able to point a mention at a task in another team or one that does not exist.
    @parameterized.expand(
        [
            ("unknown_task", {"anchor": {"kind": "document"}, "taskId": "3f1d4b7e-0000-4000-8000-000000000000"}),
            ("missing_task_id", {"anchor": {"kind": "document"}}),
            ("malformed_task_id", {"anchor": {"kind": "document"}, "taskId": "not-a-uuid"}),
        ]
    )
    def test_unresolvable_task_records_nothing(self, _name: str, context: dict):
        comment = self._comment(item_context=context)

        self._record_mentions(comment, [self.author.id])

        assert not TaskActivity.objects.filter(team=self.team).exists()

    def test_comment_from_another_product_is_ignored(self):
        comment = self._comment(scope="Insight", item_id="42")

        self._record_mentions(comment, [self.author.id])

        assert not TaskActivity.objects.filter(team=self.team).exists()


class TestForwardComment(CommentForwardingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.run = TaskRun.objects.create(team=self.team, task=self.task, status=TaskRun.Status.STARTED)
        self.task.latest_run = self.run
        self.task.save(update_fields=["latest_run"])

    def _forward(self, comment: Comment, user: User) -> str:
        return tasks_facade.forward_comment(comment.id, self.task.id, self.team.id, user.id)

    def test_author_forwards_a_comment_into_the_live_run(self):
        comment = self._comment()

        with patch.object(tasks_facade, "signal_task_run_user_message", return_value=True) as signal:
            assert self._forward(comment, self.author) == "ok"

        assert TaskCommentForward.objects.filter(team=self.team, comment=comment).exists()
        forwarded_content = signal.call_args.kwargs["content"]
        assert "this needs a guard" in forwarded_content
        # Labelled as someone's words rather than concatenated into the agent's instructions.
        assert forwarded_content.startswith("<forwarded_comment ")
        assert "Bob" in forwarded_content

    def test_only_the_task_author_may_forward(self):
        comment = self._comment()

        with patch.object(tasks_facade, "signal_task_run_user_message", return_value=True) as signal:
            assert self._forward(comment, self.peer) == "forbidden"

        signal.assert_not_called()
        assert not TaskCommentForward.objects.exists()

    def test_a_comment_reaches_the_agent_only_once(self):
        comment = self._comment()

        with patch.object(tasks_facade, "signal_task_run_user_message", return_value=True) as signal:
            assert self._forward(comment, self.author) == "ok"
            assert self._forward(comment, self.author) == "already_forwarded"

        assert signal.call_count == 1

    # The task is in the URL and the comment names its own task, so a comment belonging to a
    # different task must not be forwardable into this one's run.
    def test_comment_belonging_to_another_task_is_rejected(self):
        other_task = Task.objects.create(team=self.team, title="Other", created_by=self.author)
        comment = self._comment(item_context={"anchor": {"kind": "document"}, "taskId": str(other_task.id)})

        with patch.object(tasks_facade, "signal_task_run_user_message", return_value=True) as signal:
            assert self._forward(comment, self.author) == "not_found"

        signal.assert_not_called()

    def test_no_live_run_is_refused(self):
        self.run.status = TaskRun.Status.COMPLETED
        self.run.save(update_fields=["status"])
        comment = self._comment()

        with patch.object(tasks_facade, "signal_task_run_user_message", return_value=True) as signal:
            assert self._forward(comment, self.author) == "no_run"

        signal.assert_not_called()
        assert not TaskCommentForward.objects.exists()

    # A failed send must not burn the one shot the comment gets.
    def test_failed_signal_leaves_the_comment_forwardable(self):
        comment = self._comment()

        with patch.object(tasks_facade, "signal_task_run_user_message", return_value=False):
            assert self._forward(comment, self.author) == "signal_failed"

        assert not TaskCommentForward.objects.exists()

        with patch.object(tasks_facade, "signal_task_run_user_message", return_value=True):
            assert self._forward(comment, self.author) == "ok"
