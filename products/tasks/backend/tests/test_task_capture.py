from unittest.mock import MagicMock, patch

from django.test import TestCase

from parameterized import parameterized

from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.user import User

from products.tasks.backend.models import Channel, Task, TaskRun


class TestTaskCaptureEvent(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Northwind")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="ada@northwind.example", distinct_id="ada-distinct")

    def _task(self, **kwargs) -> Task:
        return Task.objects.create(
            team=self.team,
            title="Getting set up",
            description="prompt",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
            **kwargs,
        )

    def test_origin_key_reaches_analytics_only_when_set(self):
        capture = MagicMock()

        keyed = self._task(origin_key="desktop_onboarding_session:1")
        keyed.capture_event("task_created", capture_fn=capture)
        self.assertEqual(
            capture.call_args.kwargs["properties"]["origin_key"],
            "desktop_onboarding_session:1",
        )

        capture.reset_mock()
        unkeyed = self._task()
        unkeyed.capture_event("task_created", capture_fn=capture)
        self.assertNotIn("origin_key", capture.call_args.kwargs["properties"])

    def test_channel_id_reaches_analytics_for_space_tasks(self):
        channel = Channel.objects.unscoped().create(team=self.team, name="growth", created_by=self.user)
        capture = MagicMock()

        task = self._task(channel=channel)
        task.capture_event("task_created", capture_fn=capture)

        self.assertEqual(capture.call_args.kwargs["properties"]["channel_id"], str(channel.id))

    @parameterized.expand(
        [
            (Task.OriginProduct.SIGNALS_SCOUT, "scout-trial:00000000-0000-4000-8000-000000000001", True),
            (Task.OriginProduct.SIGNALS_SCOUT, "scheduled-scout", False),
            (Task.OriginProduct.SIGNALS_SCOUT, None, False),
            (Task.OriginProduct.USER_CREATED, "scout-trial:00000000-0000-4000-8000-000000000001", False),
        ]
    )
    def test_trial_task_and_run_captures_stay_private(
        self, origin_product: str, origin_key: str | None, suppressed: bool
    ) -> None:
        with patch("products.tasks.backend.models.posthoganalytics.capture") as capture:
            task = Task.objects.create(
                team=self.team,
                title="Test scout",
                description="Test prompt",
                origin_product=origin_product,
                origin_key=origin_key,
                created_by=self.user,
            )
            run = task.create_run(environment=TaskRun.Environment.LOCAL, extra_state={"use_dedicated_stream": False})
            task.capture_event("task_updated")
            captured = run.capture_event("task_run_completed")

        self.assertEqual(captured, not suppressed)
        events = {call.kwargs["event"] for call in capture.call_args_list}
        expected = set() if suppressed else {"task_created", "task_run_created", "task_updated", "task_run_completed"}
        self.assertEqual(events, expected)
