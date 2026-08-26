from unittest.mock import MagicMock

from django.test import TestCase

from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.user import User

from products.tasks.backend.models import Task


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
