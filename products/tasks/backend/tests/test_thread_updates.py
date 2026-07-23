from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from parameterized import parameterized

from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.scoping import team_scope

from products.tasks.backend.facade.api import (
    list_thread_messages,
    post_canvas_created_thread_update,
    post_pr_created_thread_update,
)
from products.tasks.backend.models import Channel, Task, TaskRun, TaskThreadMessage

_FLAG_TARGET = "products.tasks.backend.facade.api.posthoganalytics.feature_enabled"


class TestAgentThreadUpdates(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_user(
            email="creator@example.com", first_name="Casey", last_name="Creator", password="password"
        )
        OrganizationMembership.objects.create(user=self.user, organization=self.organization)
        # Direct instantiation sidesteps the fail-closed TeamScopedManager so
        # setUp doesn't need a team_scope wrapper (see test_channels_api.py).
        self.channel = Channel(team=self.team, name="general")
        self.channel.save()
        self.task = Task.objects.create(
            team=self.team,
            title="Build canvas",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
            channel=self.channel,
        )
        self.task_run = TaskRun.objects.create(task=self.task, team=self.team)

    def _messages(self, task: Task) -> list[TaskThreadMessage]:
        return list(TaskThreadMessage.objects.for_team(self.team.id).filter(task=task).order_by("created_at"))

    @patch(_FLAG_TARGET, return_value=True)
    def test_pr_created_posts_authorless_artifact_message(self, _flag) -> None:
        post_pr_created_thread_update(self.task_run, "https://github.com/posthog/posthog/pull/123")

        messages = self._messages(self.task)
        self.assertEqual(len(messages), 1)
        self.assertIsNone(messages[0].author_id)
        self.assertEqual(messages[0].author_kind, TaskThreadMessage.AuthorKind.AGENT)
        self.assertEqual(messages[0].event, "pr_created")
        self.assertEqual(messages[0].payload, {"pr_url": "https://github.com/posthog/posthog/pull/123"})
        self.assertEqual(
            messages[0].content,
            "[posthog/posthog#123](https://github.com/posthog/posthog/pull/123) has been opened",
        )

    @patch(_FLAG_TARGET, return_value=True)
    def test_pr_created_falls_back_to_url_label_for_non_github_urls(self, _flag) -> None:
        post_pr_created_thread_update(self.task_run, "https://example.com/pr/9")

        messages = self._messages(self.task)
        self.assertEqual(len(messages), 1)
        self.assertEqual(
            messages[0].content,
            "[https://example.com/pr/9](https://example.com/pr/9) has been opened",
        )

    @patch(_FLAG_TARGET, return_value=True)
    def test_pr_created_dedupes_per_pr_url(self, _flag) -> None:
        # Both the agent-output path and the GitHub webhook backstop can announce
        # the same PR; only one artifact row must land in the thread.
        post_pr_created_thread_update(self.task_run, "https://github.com/posthog/posthog/pull/123")
        post_pr_created_thread_update(self.task_run, "https://github.com/posthog/posthog/pull/123")

        self.assertEqual(len(self._messages(self.task)), 1)

    @patch(_FLAG_TARGET, return_value=True)
    def test_pr_created_posts_separate_messages_for_distinct_prs(self, _flag) -> None:
        post_pr_created_thread_update(self.task_run, "https://github.com/posthog/posthog/pull/1")
        post_pr_created_thread_update(self.task_run, "https://github.com/posthog/posthog/pull/2")

        self.assertEqual(len(self._messages(self.task)), 2)

    @parameterized.expand(
        [
            ("flag_off", False, True, True),
            ("no_channel", True, False, True),
            ("no_creator", True, True, False),
        ]
    )
    @patch(_FLAG_TARGET)
    def test_pr_created_skips(self, _name, flag_on, has_channel, has_creator, flag_mock) -> None:
        flag_mock.return_value = flag_on
        task = Task.objects.create(
            team=self.team,
            title="Other task",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user if has_creator else None,
            channel=self.channel if has_channel else None,
        )
        run = TaskRun.objects.create(task=task, team=self.team)

        post_pr_created_thread_update(run, "https://github.com/posthog/posthog/pull/123")

        self.assertEqual(self._messages(task), [])

    @parameterized.expand(
        [
            (
                "with_link",
                "Signups overview",
                "https://us.posthog.com/code/canvas/c/d",
                "[Signups overview](https://us.posthog.com/code/canvas/c/d) has been created",
            ),
            (
                "name_sanitized_for_link_token",
                "[Q3] KPIs",
                "https://us.posthog.com/code/canvas/c/d",
                "[Q3  KPIs](https://us.posthog.com/code/canvas/c/d) has been created",
            ),
            ("without_link", "Signups overview", None, "Signups overview has been created"),
        ]
    )
    @patch(_FLAG_TARGET, return_value=True)
    def test_canvas_created_message_content(self, _name, canvas_name, canvas_url, expected, _flag) -> None:
        post_canvas_created_thread_update(
            self.task.id, self.team.id, acting_user_id=self.user.id, canvas_name=canvas_name, canvas_url=canvas_url
        )

        messages = self._messages(self.task)
        self.assertEqual(len(messages), 1)
        self.assertIsNone(messages[0].author_id)
        self.assertEqual(messages[0].author_kind, TaskThreadMessage.AuthorKind.AGENT)
        self.assertEqual(messages[0].event, "canvas_created")
        self.assertEqual(messages[0].content, expected)

    @patch(_FLAG_TARGET, return_value=True)
    def test_canvas_created_requires_creator_match(self, _flag) -> None:
        other = User.objects.create_user(email="other@example.com", first_name="Other", password="password")

        post_canvas_created_thread_update(
            self.task.id, self.team.id, acting_user_id=other.id, canvas_name="Canvas", canvas_url=None
        )

        self.assertEqual(self._messages(self.task), [])

    @patch(_FLAG_TARGET, return_value=False)
    def test_canvas_created_skips_when_flag_off(self, _flag) -> None:
        post_canvas_created_thread_update(
            self.task.id, self.team.id, acting_user_id=self.user.id, canvas_name="Canvas", canvas_url=None
        )

        self.assertEqual(self._messages(self.task), [])

    def test_list_thread_messages_excludes_legacy_turn_complete_rows(self) -> None:
        # The thread is human-to-human plus artifacts: rows written back when the
        # agent finished a turn (before that writeback was removed) must not
        # resurface in the listing.
        TaskThreadMessage.objects.for_team(self.team.id).create(
            team=self.team, task=self.task, author=self.user, content="Kicking this off"
        )
        TaskThreadMessage.objects.for_team(self.team.id).create(
            team=self.team,
            task=self.task,
            author_kind=TaskThreadMessage.AuthorKind.AGENT,
            event="turn_complete",
            payload={"run_id": str(self.task_run.id)},
            content="@[Casey Creator](creator@example.com) Turn complete.",
        )
        TaskThreadMessage.objects.for_team(self.team.id).create(
            team=self.team,
            task=self.task,
            author_kind=TaskThreadMessage.AuthorKind.AGENT,
            event="canvas_created",
            payload={"canvas_name": "Signups", "canvas_url": None},
            content="Signups has been created",
        )

        with team_scope(self.team.id):
            messages = list_thread_messages(self.task.id, self.team.id, self.user.id)

        assert messages is not None
        self.assertEqual([message.event for message in messages], ["", "canvas_created"])
