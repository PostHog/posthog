from datetime import timedelta

import pytest
from posthog.test.base import APIBaseTest

from django.utils import timezone

from rest_framework import status

from products.uptime.backend.facade import api
from products.uptime.backend.facade.contracts import CreateIncidentInput, UpdateIncidentInput
from products.uptime.backend.logic import create_status_page, publish_status_page, update_status_page
from products.uptime.backend.models import Incident, Monitor
from products.uptime.backend.tests.conftest import UptimeTeamScopedTestMixin


@pytest.mark.django_db
class TestIncidentAPI:
    def test_create_sets_started_at_default(self, team):
        monitor = Monitor.objects.create(team_id=team.id, name="m", url="https://example.com")
        dto = api.create_incident(
            CreateIncidentInput(team_id=team.id, monitor_id=monitor.id, name="Outage", description="API down")
        )
        assert dto.name == "Outage"
        assert dto.description == "API down"
        assert dto.monitor_id == monitor.id
        assert dto.resolved_at is None
        assert dto.started_at is not None

    def test_list_orders_ongoing_first(self, team):
        monitor = Monitor.objects.create(team_id=team.id, name="m", url="https://example.com")
        Incident.objects.create(
            team_id=team.id,
            monitor=monitor,
            name="Old resolved",
            started_at=timezone.now() - timedelta(days=2),
            resolved_at=timezone.now() - timedelta(days=1),
        )
        ongoing = Incident.objects.create(
            team_id=team.id,
            monitor=monitor,
            name="Still ongoing",
            started_at=timezone.now() - timedelta(hours=1),
        )

        result = api.list_incidents(team_id=team.id)
        assert [i.id for i in result] == [ongoing.id, result[1].id]
        assert result[0].resolved_at is None

    def test_update_clears_resolved_at(self, team):
        monitor = Monitor.objects.create(team_id=team.id, name="m", url="https://example.com")
        dto = api.create_incident(CreateIncidentInput(team_id=team.id, monitor_id=monitor.id, name="i1"))
        # Resolve it
        api.update_incident(UpdateIncidentInput(team_id=team.id, incident_id=dto.id, resolved_at=timezone.now()))
        # Reopen by clearing
        reopened = api.update_incident(UpdateIncidentInput(team_id=team.id, incident_id=dto.id, clear_resolved_at=True))
        assert reopened.resolved_at is None


class TestIncidentEndpoints(UptimeTeamScopedTestMixin, APIBaseTest):
    def _url(self, suffix: str = "") -> str:
        return f"/api/environments/{self.team.id}/uptime/incidents/{suffix}"

    def test_create_requires_existing_monitor_for_team(self) -> None:
        # No monitors exist yet, so any monitor_id should fail.
        response = self.client.post(
            self._url(),
            data={"monitor_id": "00000000-0000-0000-0000-000000000000", "name": "x"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_and_list_and_resolve(self) -> None:
        monitor = Monitor.objects.create(team_id=self.team.id, name="m", url="https://example.com")
        create_response = self.client.post(
            self._url(),
            data={"monitor_id": str(monitor.id), "name": "Outage", "description": "API down"},
            format="json",
        )
        assert create_response.status_code == status.HTTP_201_CREATED
        incident_id = create_response.json()["id"]

        list_response = self.client.get(self._url())
        assert list_response.status_code == status.HTTP_200_OK
        assert [i["id"] for i in list_response.json()] == [incident_id]

        # Filter by monitor_id
        filtered = self.client.get(f"{self._url()}?monitor_id={monitor.id}")
        assert filtered.status_code == status.HTTP_200_OK
        assert len(filtered.json()) == 1

        # Resolve requires a note
        rejected = self.client.post(f"{self._url()}{incident_id}/resolve/", data={}, format="json")
        assert rejected.status_code == status.HTTP_400_BAD_REQUEST

        resolved = self.client.post(
            f"{self._url()}{incident_id}/resolve/",
            data={"resolution_note": "Bounced the proxy."},
            format="json",
        )
        assert resolved.status_code == status.HTTP_200_OK
        assert resolved.json()["resolved_at"] is not None
        assert resolved.json()["resolution_note"] == "Bounced the proxy."

        # Reopen clears the note
        reopened = self.client.post(f"{self._url()}{incident_id}/reopen/")
        assert reopened.status_code == status.HTTP_200_OK
        assert reopened.json()["resolved_at"] is None
        assert reopened.json()["resolution_note"] == ""

    def test_patch_can_clear_resolved_at_via_null(self) -> None:
        monitor = Monitor.objects.create(team_id=self.team.id, name="m", url="https://example.com")
        incident = Incident.objects.create(
            team_id=self.team.id,
            monitor=monitor,
            name="resolved",
            started_at=timezone.now() - timedelta(hours=1),
            resolved_at=timezone.now(),
        )
        response = self.client.patch(
            f"{self._url()}{incident.id}/",
            data={"resolved_at": None},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["resolved_at"] is None

    def test_delete_removes_incident(self) -> None:
        monitor = Monitor.objects.create(team_id=self.team.id, name="m", url="https://example.com")
        incident = Incident.objects.create(team_id=self.team.id, monitor=monitor, name="i", started_at=timezone.now())
        response = self.client.delete(f"{self._url()}{incident.id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Incident.objects.filter(id=incident.id).exists()


class TestPublicStatusPageIncidents(UptimeTeamScopedTestMixin, APIBaseTest):
    def test_public_page_returns_ongoing_and_recent_incidents(self) -> None:
        monitor = Monitor.objects.create(team_id=self.team.id, name="m", url="https://example.com")
        page = create_status_page(team_id=self.team.id)
        update_status_page(team_id=self.team.id, page_id=page.id, monitor_ids=[monitor.id])
        publish_status_page(team_id=self.team.id, page_id=page.id)

        Incident.objects.create(team_id=self.team.id, monitor=monitor, name="Ongoing", started_at=timezone.now())
        Incident.objects.create(
            team_id=self.team.id,
            monitor=monitor,
            name="Recent",
            started_at=timezone.now() - timedelta(hours=2),
            resolved_at=timezone.now() - timedelta(hours=1),
        )
        # Older than 7 days — should be excluded from the public page
        Incident.objects.create(
            team_id=self.team.id,
            monitor=monitor,
            name="Stale",
            started_at=timezone.now() - timedelta(days=30),
            resolved_at=timezone.now() - timedelta(days=20),
        )

        self.client.logout()
        response = self.client.get(f"/api/uptime/public_status_pages/{page.slug}/")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert [i["name"] for i in body["ongoing_incidents"]] == ["Ongoing"]
        assert [i["name"] for i in body["recent_incidents"]] == ["Recent"]
