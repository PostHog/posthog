from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import APIBaseTest

from django.db import connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team
from posthog.models.organization_ip_restrictions import OrganizationIPRestrictions
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

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

    @parameterized.expand(
        [
            (credential, operation)
            for credential in ("session", "personal_api_key")
            for operation in ("list", "retrieve", "update", "delete", "create", "move")
        ]
    )
    @time_machine.travel("2026-01-15T12:00:00Z", tick=False)
    def test_ip_policy_applies_to_reminder_organization(self, credential: str, operation: str) -> None:
        other = Organization.objects.create(name="Other example organization")
        other_team = Team.objects.create(organization=other)
        self.user.join(organization=other)
        self.user.current_organization = other
        self.user.current_team = other_team
        self.user.save()
        scheduled_at = datetime.now(UTC) + timedelta(days=1)
        blocked = Reminder.objects.create(
            organization=self.organization, created_by=self.user, title="Restricted reminder", scheduled_at=scheduled_at
        )
        allowed = Reminder.objects.create(
            organization=other, created_by=self.user, title="Available reminder", scheduled_at=scheduled_at
        )
        OrganizationIPRestrictions.objects.create(organization=self.organization, ip_restrictions=["203.0.113.0/24"])
        if credential == "personal_api_key":
            self.client.logout()
            token = generate_random_token_personal()
            PersonalAPIKey.objects.create(
                user=self.user,
                label="Reminder example key",
                secure_value=hash_key_value(token),
                scopes=["user:read", "user:write"],
            )
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.client.defaults["REMOTE_ADDR"] = "198.51.100.7"
        with CaptureQueriesContext(connection) as queries:
            if operation == "list":
                response = self.client.get(self._url())
                self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
                self.assertEqual([row["id"] for row in response.json()["results"]], [str(allowed.id)])
            elif operation == "create":
                response = self.client.post(self._url(), self._payload())
            elif operation == "move":
                response = self.client.patch(self._url(f"{allowed.id}/"), {"organization": str(self.organization.id)})
            else:
                method = {"retrieve": "get", "update": "patch", "delete": "delete"}[operation]
                response = getattr(self.client, method)(self._url(f"{blocked.id}/"), {"title": "Updated reminder"})
        if operation != "list":
            expected = status.HTTP_403_FORBIDDEN if operation in ("create", "move") else status.HTTP_404_NOT_FOUND
            self.assertEqual(response.status_code, expected, response.content)
        policy_reads = [
            query for query in queries.captured_queries if 'FROM "posthog_organizationiprestrictions"' in query["sql"]
        ]
        self.assertEqual(len(policy_reads), 1)
        blocked.refresh_from_db()
        allowed.refresh_from_db()
        self.assertEqual(blocked.title, "Restricted reminder")
        self.assertFalse(blocked.deleted)
        self.assertEqual(allowed.organization_id, other.id)
        self.assertEqual(Reminder.objects.count(), 2)

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

    def test_list_pages_are_stable_when_created_at_ties(self) -> None:
        future = datetime.now(UTC) + timedelta(days=1)
        reminders = [
            Reminder.objects.create(
                organization=self.organization,
                created_by=self.user,
                title=f"r{i}",
                scheduled_at=future,
                next_fire_at=future,
            )
            for i in range(5)
        ]
        tied, older = reminders[:4], reminders[4]
        # uuid7 keys rise with insertion order, so the oldest row here also holds the highest id.
        # Both ordering terms are then load-bearing in the sequence below.
        tied_at = datetime.now(UTC) - timedelta(hours=1)
        Reminder.objects.filter(id__in=[r.id for r in tied]).update(created_at=tied_at)
        Reminder.objects.filter(id=older.id).update(created_at=tied_at - timedelta(hours=1))

        paged: list[str] = []
        for offset in (0, 2, 4):
            response = self.client.get(self._url(f"?limit=2&offset={offset}"))
            self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
            paged.extend(r["id"] for r in response.json()["results"])

        expected = [str(r.id) for r in sorted(tied, key=lambda r: r.id, reverse=True)] + [str(older.id)]
        self.assertEqual(paged, expected)
