from unittest.mock import patch

from django.test import TestCase

from posthog.models import Organization, Team, User

from products.tasks.backend.loop_lifecycle import DISABLED_REASON_OWNER_DEACTIVATED, pause_loops_for_deactivated_user
from products.tasks.backend.models import Loop

LIFECYCLE_MODULE = "products.tasks.backend.loop_lifecycle"


class TestPauseLoopsForDeactivatedUser(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_user(email="owner@example.com", first_name="Owner", password="password")

    def _loop(self, **overrides) -> Loop:
        defaults = {
            "team": self.team,
            "created_by": self.user,
            "name": "Daily digest",
            "instructions": "Summarize",
            "runtime_adapter": "claude",
            "model": "claude-sonnet-5",
            "enabled": True,
        }
        defaults.update(overrides)
        return Loop.objects.unscoped().create(**defaults)

    @patch(f"{LIFECYCLE_MODULE}.pause_loop_schedules")
    @patch(f"{LIFECYCLE_MODULE}.dispatch_loop_event")
    def test_deactivation_pauses_records_reason_and_notifies(self, mock_dispatch, _mock_pause):
        loop = self._loop()

        pause_loops_for_deactivated_user(self.user.id)

        loop.refresh_from_db()
        self.assertFalse(loop.enabled)
        self.assertEqual(loop.disabled_reason, DISABLED_REASON_OWNER_DEACTIVATED)
        reasons = [call.args[2].get("reason") for call in mock_dispatch.call_args_list if len(call.args) >= 3]
        self.assertIn(DISABLED_REASON_OWNER_DEACTIVATED, reasons)
