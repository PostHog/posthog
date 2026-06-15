from datetime import UTC, datetime

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

from products.reminders.backend.firing import process_due_reminders
from products.reminders.backend.models import Reminder


class TestProcessDueReminders(BaseTest):
    @freeze_time("2026-06-15T09:00:00Z")
    @patch("products.reminders.backend.firing.create_notification")
    def test_one_off_fires_and_completes(self, mock_create: object) -> None:
        reminder = Reminder.objects.unscoped().create(
            team=self.team,
            created_by=self.user,
            title="Check funnel",
            scheduled_at=datetime(2026, 6, 15, 8, 59, tzinfo=UTC),
            next_fire_at=datetime(2026, 6, 15, 8, 59, tzinfo=UTC),
        )
        process_due_reminders()
        mock_create.assert_called_once()
        reminder.refresh_from_db()
        self.assertEqual(reminder.status, Reminder.Status.COMPLETED)
        self.assertEqual(reminder.last_fired_at, datetime(2026, 6, 15, 9, 0, tzinfo=UTC))

    @freeze_time("2026-06-15T09:00:00Z")
    @patch("products.reminders.backend.firing.create_notification")
    def test_recurring_advances_and_stays_active(self, mock_create: object) -> None:
        reminder = Reminder.objects.unscoped().create(
            team=self.team,
            created_by=self.user,
            title="Daily",
            recurrence_interval="daily",
            next_fire_at=datetime(2026, 6, 15, 8, 59, tzinfo=UTC),
        )
        process_due_reminders()
        reminder.refresh_from_db()
        self.assertEqual(reminder.status, Reminder.Status.ACTIVE)
        self.assertEqual(reminder.next_fire_at, datetime(2026, 6, 16, 8, 59, tzinfo=UTC))

    @freeze_time("2026-06-15T09:00:00Z")
    @patch("products.reminders.backend.firing.create_notification")
    def test_not_yet_due_is_skipped(self, mock_create: object) -> None:
        Reminder.objects.unscoped().create(
            team=self.team,
            created_by=self.user,
            title="Later",
            scheduled_at=datetime(2026, 6, 15, 10, 0, tzinfo=UTC),
            next_fire_at=datetime(2026, 6, 15, 10, 0, tzinfo=UTC),
        )
        process_due_reminders()
        mock_create.assert_not_called()

    @freeze_time("2026-06-15T09:00:00Z")
    @patch("products.reminders.backend.firing.create_notification")
    def test_recurring_catch_up_fires_once(self, mock_create: object) -> None:
        reminder = Reminder.objects.unscoped().create(
            team=self.team,
            created_by=self.user,
            title="Daily",
            recurrence_interval="daily",
            next_fire_at=datetime(2026, 6, 10, 8, 59, tzinfo=UTC),
        )
        process_due_reminders()
        mock_create.assert_called_once()
        reminder.refresh_from_db()
        self.assertGreater(reminder.next_fire_at, datetime(2026, 6, 15, 9, 0, tzinfo=UTC))

    @freeze_time("2026-06-15T09:00:00Z")
    @patch("products.reminders.backend.firing.create_notification", side_effect=RuntimeError("boom"))
    def test_one_off_errors_after_retries(self, mock_create: object) -> None:
        reminder = Reminder.objects.unscoped().create(
            team=self.team,
            created_by=self.user,
            title="Boom",
            scheduled_at=datetime(2026, 6, 15, 8, 59, tzinfo=UTC),
            next_fire_at=datetime(2026, 6, 15, 8, 59, tzinfo=UTC),
            failure_count=4,
        )
        process_due_reminders()
        reminder.refresh_from_db()
        self.assertEqual(reminder.status, Reminder.Status.ERRORED)
        self.assertIn("boom", reminder.last_error or "")
