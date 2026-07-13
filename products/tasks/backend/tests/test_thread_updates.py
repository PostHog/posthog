from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from parameterized import parameterized

from posthog.models import Organization, OrganizationMembership, Team, User

from products.tasks.backend.facade.api import post_canvas_created_thread_update, post_turn_complete_thread_update
from products.tasks.backend.models import Channel, Task, TaskRun, TaskThreadMessage, TaskThreadMessageMention

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
        self.channel = Channel.objects.create(team=self.team, name="general")
        self.task = Task.objects.create(
            team=self.team,
            title="Build canvas",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
            channel=self.channel,
        )
        self.run = TaskRun.objects.create(task=self.task, team=self.team)

    def _messages(self, task: Task) -> list[TaskThreadMessage]:
        return list(TaskThreadMessage.objects.for_team(self.team.id).filter(task=task).order_by("created_at"))

    @patch(_FLAG_TARGET, return_value=True)
    def test_turn_complete_posts_authorless_message_mentioning_creator(self, _flag) -> None:
        post_turn_complete_thread_update(str(self.run.id), str(self.task.id), self.team.id)

        messages = self._messages(self.task)
        self.assertEqual(len(messages), 1)
        self.assertIsNone(messages[0].author_id)
        self.assertEqual(messages[0].content, "@[Casey Creator](creator@example.com) Turn complete.")
        # The creator's mention is indexed so it lands in their mentions feed.
        self.assertTrue(
            TaskThreadMessageMention.objects.for_team(self.team.id)
            .filter(message=messages[0], mentioned_user=self.user)
            .exists()
        )

    @patch(_FLAG_TARGET, return_value=True)
    def test_turn_complete_cooldown_collapses_duplicate_end_of_turn_events(self, _flag) -> None:
        post_turn_complete_thread_update(str(self.run.id), str(self.task.id), self.team.id)
        post_turn_complete_thread_update(str(self.run.id), str(self.task.id), self.team.id)

        self.assertEqual(len(self._messages(self.task)), 1)

    @parameterized.expand(
        [
            ("flag_off", False, True, True),
            ("no_channel", True, False, True),
            ("no_creator", True, True, False),
        ]
    )
    @patch(_FLAG_TARGET)
    def test_turn_complete_skips(self, _name, flag_on, has_channel, has_creator, flag_mock) -> None:
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

        post_turn_complete_thread_update(str(run.id), str(task.id), self.team.id)

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
        post_canvas_created_thread_update(self.task.id, self.team.id, canvas_name=canvas_name, canvas_url=canvas_url)

        messages = self._messages(self.task)
        self.assertEqual(len(messages), 1)
        self.assertIsNone(messages[0].author_id)
        self.assertEqual(messages[0].content, expected)

    @patch(_FLAG_TARGET, return_value=False)
    def test_canvas_created_skips_when_flag_off(self, _flag) -> None:
        post_canvas_created_thread_update(self.task.id, self.team.id, canvas_name="Canvas", canvas_url=None)

        self.assertEqual(self._messages(self.task), [])
