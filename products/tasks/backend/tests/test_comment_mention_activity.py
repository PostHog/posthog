from django.test import TestCase

from parameterized import parameterized

from posthog.models import Comment, Organization, OrganizationMembership, Team, User

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.models import Task, TaskActivity


class CommentMentionTestCase(TestCase):
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


class TestCommentMentionActivity(CommentMentionTestCase):
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
