from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import Team

from products.reminders.backend.models import Reminder


class TestReminderAPI(APIBaseTest):
    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/reminders/{suffix}"

    def test_create_one_off_reminder(self) -> None:
        future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        response = self.client.post(self._url(), {"title": "Check funnel", "scheduled_at": future})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        body = response.json()
        self.assertEqual(body["title"], "Check funnel")
        self.assertEqual(body["status"], "active")
        reminder = Reminder.objects.unscoped().get(id=body["id"])
        self.assertEqual(reminder.created_by, self.user)
        assert reminder.next_fire_at is not None
        self.assertEqual(reminder.next_fire_at.isoformat(), future)

    def test_create_recurring_cron_reminder(self) -> None:
        response = self.client.post(
            self._url(),
            {"title": "Weekly review", "cron_expression": "0 9 * * 1", "timezone": "America/New_York"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        reminder = Reminder.objects.unscoped().get(id=response.json()["id"])
        self.assertIsNotNone(reminder.next_fire_at)

    def test_rejects_two_schedule_sources(self) -> None:
        future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        response = self.client.post(self._url(), {"title": "x", "scheduled_at": future, "recurrence_interval": "daily"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_no_schedule(self) -> None:
        response = self.client.post(self._url(), {"title": "x"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_too_frequent_cron(self) -> None:
        response = self.client.post(self._url(), {"title": "x", "cron_expression": "*/10 * * * *"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_past_scheduled_at(self) -> None:
        past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        response = self.client.post(self._url(), {"title": "x", "scheduled_at": past})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_missing_resource(self) -> None:
        future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        response = self.client.post(
            self._url(),
            {"title": "x", "scheduled_at": future, "resource_type": "dashboard", "resource_id": "99999"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_invalid_timezone(self) -> None:
        future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        response = self.client.post(self._url(), {"title": "x", "scheduled_at": future, "timezone": "Mars/Phobos"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_active_cap_enforced(self) -> None:
        for i in range(50):
            Reminder.objects.unscoped().create(
                team=self.team,
                created_by=self.user,
                title=f"r{i}",
                scheduled_at=datetime.now(UTC) + timedelta(days=1),
                next_fire_at=datetime.now(UTC) + timedelta(days=1),
            )
        future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        response = self.client.post(self._url(), {"title": "over", "scheduled_at": future})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_only_returns_own_reminders(self) -> None:
        other = self._create_user("other@posthog.com")
        Reminder.objects.unscoped().create(
            team=self.team,
            created_by=other,
            title="theirs",
            scheduled_at=datetime.now(UTC) + timedelta(days=1),
            next_fire_at=datetime.now(UTC) + timedelta(days=1),
        )
        Reminder.objects.unscoped().create(
            team=self.team,
            created_by=self.user,
            title="mine",
            scheduled_at=datetime.now(UTC) + timedelta(days=1),
            next_fire_at=datetime.now(UTC) + timedelta(days=1),
        )
        response = self.client.get(self._url())
        titles = [r["title"] for r in response.json()["results"]]
        self.assertEqual(titles, ["mine"])

    def test_cannot_get_others_reminder(self) -> None:
        other = self._create_user("other2@posthog.com")
        reminder = Reminder.objects.unscoped().create(
            team=self.team,
            created_by=other,
            title="theirs",
            scheduled_at=datetime.now(UTC) + timedelta(days=1),
            next_fire_at=datetime.now(UTC) + timedelta(days=1),
        )
        response = self.client.get(self._url(f"{reminder.id}/"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_soft_deletes(self) -> None:
        reminder = Reminder.objects.unscoped().create(
            team=self.team,
            created_by=self.user,
            title="mine",
            scheduled_at=datetime.now(UTC) + timedelta(days=1),
            next_fire_at=datetime.now(UTC) + timedelta(days=1),
        )
        response = self.client.delete(self._url(f"{reminder.id}/"))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        reminder.refresh_from_db()
        self.assertTrue(reminder.deleted)

    def test_reminder_in_team_a_not_visible_under_team_b(self) -> None:
        team_b = Team.objects.create(organization=self.organization, name="B")
        r_a = Reminder.objects.unscoped().create(
            team=self.team,
            created_by=self.user,
            title="x",
            scheduled_at=datetime.now(UTC) + timedelta(days=1),
            next_fire_at=datetime.now(UTC) + timedelta(days=1),
        )
        list_resp = self.client.get(f"/api/projects/{team_b.id}/reminders/")
        self.assertNotIn(str(r_a.id), [r["id"] for r in list_resp.json()["results"]])
        self.assertEqual(self.client.get(f"/api/projects/{team_b.id}/reminders/{r_a.id}/").status_code, 404)
