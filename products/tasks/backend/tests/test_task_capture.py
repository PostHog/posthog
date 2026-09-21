from unittest.mock import MagicMock

from django.test import TestCase

from parameterized import parameterized

from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.user import User

from products.tasks.backend.models import Channel, Task


class TestTaskCaptureEvent(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Northwind")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="ada@northwind.example", distinct_id="ada-distinct")

    def _task(self, **kwargs) -> Task:
        kwargs.setdefault("origin_product", Task.OriginProduct.USER_CREATED)
        return Task.objects.create(
            team=self.team,
            title="Getting set up",
            description="prompt",
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
            (Task.OriginProduct.USER_CREATED, False, False),
            (Task.OriginProduct.WORKFLOW, False, False),
            (Task.OriginProduct.SIGNALS_SCOUT, False, True),
            (Task.OriginProduct.SIGNAL_REPORT, True, True),
        ]
    )
    def test_origin_marks_fleet_traffic_in_analytics(self, origin_product, internal, is_platform_origin):
        capture = MagicMock()

        task = self._task(origin_product=origin_product, internal=internal)
        task.capture_event("task_run_created", capture_fn=capture)

        properties = capture.call_args.kwargs["properties"]
        self.assertEqual(properties["internal"], internal)
        self.assertEqual(properties["is_platform_origin"], is_platform_origin)
