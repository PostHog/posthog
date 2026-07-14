from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from parameterized import parameterized

from posthog.models import Organization, OrganizationMembership, Team, User

from products.tasks.backend.facade.api import post_canvas_created_thread_update, post_turn_complete_thread_update
from products.tasks.backend.models import Channel, Task, TaskRun, TaskThreadMessage, TaskThreadMessageMention
from products.tasks.backend.temporal.process_task.activities.relay_sandbox_events import _track_final_message

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

    @parameterized.expand(
        [
            (
                "relays_final_message",
                "Shipped the canvas with three charts.",
                "@[Casey Creator](creator@example.com) Shipped the canvas with three charts.",
            ),
            ("falls_back_without_message", None, "@[Casey Creator](creator@example.com) Turn complete."),
        ]
    )
    @patch(_FLAG_TARGET, return_value=True)
    def test_turn_complete_posts_authorless_message_mentioning_creator(self, _name, message, expected, _flag) -> None:
        post_turn_complete_thread_update(str(self.task_run.id), str(self.task.id), self.team.id, message=message)

        messages = self._messages(self.task)
        self.assertEqual(len(messages), 1)
        self.assertIsNone(messages[0].author_id)
        self.assertEqual(messages[0].author_kind, TaskThreadMessage.AuthorKind.AGENT)
        self.assertEqual(messages[0].event, "turn_complete")
        # run_id is the client's key for deduping this durable row against
        # live session-derived agent turns.
        self.assertEqual(messages[0].payload, {"run_id": str(self.task_run.id)})
        self.assertEqual(messages[0].content, expected)
        # The creator's mention is indexed so it lands in their mentions feed.
        self.assertTrue(
            TaskThreadMessageMention.objects.for_team(self.team.id)
            .filter(message=messages[0], mentioned_user=self.user)
            .exists()
        )

    @patch(_FLAG_TARGET, return_value=True)
    def test_turn_complete_truncates_oversized_message(self, _flag) -> None:
        post_turn_complete_thread_update(str(self.task_run.id), str(self.task.id), self.team.id, message="x" * 5000)

        content = self._messages(self.task)[0].content
        self.assertTrue(content.endswith("…"))
        self.assertLess(len(content), 4100)

    @patch(_FLAG_TARGET, return_value=True)
    def test_turn_complete_cooldown_collapses_duplicate_end_of_turn_events(self, _flag) -> None:
        post_turn_complete_thread_update(str(self.task_run.id), str(self.task.id), self.team.id)
        post_turn_complete_thread_update(str(self.task_run.id), str(self.task.id), self.team.id)

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


def _session_update(update: dict) -> dict:
    return {"type": "notification", "notification": {"method": "session/update", "params": {"update": update}}}


def _chunk(text: str) -> dict:
    return _session_update({"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}})


class TestTrackFinalMessage(SimpleTestCase):
    def test_holds_only_prose_after_last_tool_call(self) -> None:
        parts: list[str] = []
        for event in [
            _chunk("Let me look at the data first. "),
            _session_update({"sessionUpdate": "tool_call", "toolCallId": "t1"}),
            _session_update({"sessionUpdate": "tool_call_update", "toolCallId": "t1"}),
            _chunk("Done. The canvas "),
            _chunk("shows signups by week."),
        ]:
            _track_final_message(event, parts)

        self.assertEqual("".join(parts), "Done. The canvas shows signups by week.")

    @parameterized.expand([("user_message",), ("user_message_chunk",), ("tool_call",)])
    def test_resets_on(self, session_update: str) -> None:
        parts = ["stale narration"]

        _track_final_message(_session_update({"sessionUpdate": session_update}), parts)

        self.assertEqual(parts, [])
