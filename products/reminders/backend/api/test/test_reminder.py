from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import Organization, Team

from products.reminders.backend.models import Reminder


class TestReminderAPI(APIBaseTest):
    def _url(self, suffix: str = "") -> str:
        return f"/api/reminders/{suffix}"

    def _payload(self, **overrides: object) -> dict[str, object]:
        future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        payload: dict[str, object] = {
            "organization": str(self.organization.id),
            "title": "Check funnel",
            "scheduled_at": future,
        }
        payload.update(overrides)
        return payload

    def test_create_one_off_reminder(self) -> None:
        future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        response = self.client.post(self._url(), self._payload(scheduled_at=future))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        body = response.json()
        self.assertEqual(body["title"], "Check funnel")
        self.assertEqual(body["status"], "active")
        reminder = Reminder.objects.get(id=body["id"])
        self.assertEqual(reminder.created_by, self.user)
        self.assertEqual(reminder.organization_id, self.organization.id)
        assert reminder.next_fire_at is not None
        self.assertEqual(reminder.next_fire_at.isoformat(), future)

    def test_create_recurring_cron_reminder(self) -> None:
        response = self.client.post(
            self._url(),
            self._payload(
                title="Weekly review",
                scheduled_at=None,
                cron_expression="0 9 * * 1",
                timezone="America/New_York",
            ),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        reminder = Reminder.objects.get(id=response.json()["id"])
        self.assertIsNotNone(reminder.next_fire_at)

    def test_create_with_team(self) -> None:
        response = self.client.post(self._url(), self._payload(team=self.team.id))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        reminder = Reminder.objects.get(id=response.json()["id"])
        self.assertEqual(reminder.team_id, self.team.id)

    def test_rejects_two_schedule_sources(self) -> None:
        response = self.client.post(self._url(), self._payload(recurrence_interval="daily"))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_no_schedule(self) -> None:
        response = self.client.post(self._url(), self._payload(scheduled_at=None))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_too_frequent_cron(self) -> None:
        response = self.client.post(self._url(), self._payload(scheduled_at=None, cron_expression="*/10 * * * *"))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_past_scheduled_at(self) -> None:
        past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        response = self.client.post(self._url(), self._payload(scheduled_at=past))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_completed_one_off_title_allowed(self) -> None:
        reminder = Reminder.objects.create(
            organization=self.organization,
            created_by=self.user,
            title="old",
            status=Reminder.Status.COMPLETED,
            scheduled_at=datetime.now(UTC) - timedelta(days=1),
            next_fire_at=datetime.now(UTC) - timedelta(days=1),
        )
        response = self.client.patch(self._url(f"{reminder.id}/"), {"title": "new"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        reminder.refresh_from_db()
        self.assertEqual(reminder.title, "new")
        self.assertEqual(reminder.status, Reminder.Status.COMPLETED)

    def test_rejects_resource_without_team(self) -> None:
        response = self.client.post(
            self._url(),
            self._payload(resource_type="dashboard", resource_id="99999"),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_missing_resource_in_team(self) -> None:
        response = self.client.post(
            self._url(),
            self._payload(team=self.team.id, resource_type="dashboard", resource_id="99999"),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_invalid_timezone(self) -> None:
        response = self.client.post(self._url(), self._payload(timezone="Mars/Phobos"))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_organization_user_is_not_member_of(self) -> None:
        other_org = Organization.objects.create(name="Other")
        response = self.client.post(self._url(), self._payload(organization=str(other_org.id)))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_team_in_other_organization(self) -> None:
        other_org = Organization.objects.create(name="Other")
        other_team = Team.objects.create(organization=other_org, name="Other team")
        response = self.client.post(self._url(), self._payload(team=other_team.id))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_active_cap_enforced(self) -> None:
        for i in range(50):
            Reminder.objects.create(
                organization=self.organization,
                created_by=self.user,
                title=f"r{i}",
                scheduled_at=datetime.now(UTC) + timedelta(days=1),
                next_fire_at=datetime.now(UTC) + timedelta(days=1),
            )
        response = self.client.post(self._url(), self._payload(title="over"))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_only_returns_own_reminders(self) -> None:
        other = self._create_user("other@posthog.com")
        Reminder.objects.create(
            organization=self.organization,
            created_by=other,
            title="theirs",
            scheduled_at=datetime.now(UTC) + timedelta(days=1),
            next_fire_at=datetime.now(UTC) + timedelta(days=1),
        )
        Reminder.objects.create(
            organization=self.organization,
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
        reminder = Reminder.objects.create(
            organization=self.organization,
            created_by=other,
            title="theirs",
            scheduled_at=datetime.now(UTC) + timedelta(days=1),
            next_fire_at=datetime.now(UTC) + timedelta(days=1),
        )
        response = self.client.get(self._url(f"{reminder.id}/"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_soft_deletes(self) -> None:
        reminder = Reminder.objects.create(
            organization=self.organization,
            created_by=self.user,
            title="mine",
            scheduled_at=datetime.now(UTC) + timedelta(days=1),
            next_fire_at=datetime.now(UTC) + timedelta(days=1),
        )
        response = self.client.delete(self._url(f"{reminder.id}/"))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        reminder.refresh_from_db()
        self.assertTrue(reminder.deleted)
