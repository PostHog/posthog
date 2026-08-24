from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.scoping import team_scope

from products.error_tracking.backend.models import ErrorTrackingAlert


class TestErrorTrackingAlerts(APIBaseTest):
    def _create_slack_integration(self, team=None) -> Integration:
        return Integration.objects.create(
            team=team or self.team,
            kind=Integration.IntegrationKind.SLACK.value,
            config={"team": {"id": "T123"}},
            sensitive_config={"access_token": "token"},
        )

    def _valid_payload(self, integration: Integration, **overrides) -> dict:
        payload = {
            "name": "Notify #alerts",
            "triggers": ["issue_created", "issue_spiking"],
            "channel_type": "slack",
            "integration_id": integration.id,
            "config": {"channel": "C0123"},
        }
        payload.update(overrides)
        return payload

    def test_alert_crud_roundtrip(self):
        integration = self._create_slack_integration()

        create = self.client.post(
            f"/api/projects/{self.team.id}/error_tracking/alerts/",
            data=self._valid_payload(integration),
            format="json",
        )
        assert create.status_code == 201, create.json()
        created = create.json()
        assert created["name"] == "Notify #alerts"
        assert created["enabled"] is True
        assert created["triggers"] == ["issue_created", "issue_spiking"]
        assert created["channel_type"] == "slack"
        assert created["integration_id"] == integration.id
        assert created["config"] == {"channel": "C0123"}

        alert_id = created["id"]
        update = self.client.patch(
            f"/api/projects/{self.team.id}/error_tracking/alerts/{alert_id}/",
            data={"enabled": False, "triggers": ["issue_reopened"]},
            format="json",
        )
        assert update.status_code == 200, update.json()
        assert update.json()["enabled"] is False
        assert update.json()["triggers"] == ["issue_reopened"]

        listing = self.client.get(f"/api/projects/{self.team.id}/error_tracking/alerts/")
        assert listing.status_code == 200
        assert [alert["id"] for alert in listing.json()["results"]] == [alert_id]

        delete = self.client.delete(f"/api/projects/{self.team.id}/error_tracking/alerts/{alert_id}/")
        assert delete.status_code == 204
        assert self.client.get(f"/api/projects/{self.team.id}/error_tracking/alerts/{alert_id}/").status_code == 404

    @parameterized.expand(
        [
            ("unknown_trigger", {"triggers": ["issue_deleted"]}),
            ("empty_triggers", {"triggers": []}),
            ("unknown_channel", {"channel_type": "carrier_pigeon"}),
            ("missing_integration", {"integration_id": None}),
            ("missing_channel_in_config", {"config": {}}),
            ("null_config", {"config": None}),
            ("non_object_config", {"config": "C0123"}),
            ("array_config", {"config": ["C0123"]}),
        ]
    )
    def test_alert_create_rejects_invalid_payload(self, _name, overrides):
        integration = self._create_slack_integration()

        response = self.client.post(
            f"/api/projects/{self.team.id}/error_tracking/alerts/",
            data=self._valid_payload(integration, **overrides),
            format="json",
        )

        assert response.status_code == 400, response.json()
        assert ErrorTrackingAlert.objects.for_team(self.team.id).count() == 0

    def test_alert_create_rejects_other_teams_integration(self):
        other_team = self.create_team_with_organization(organization=self.organization)
        foreign_integration = self._create_slack_integration(team=other_team)

        response = self.client.post(
            f"/api/projects/{self.team.id}/error_tracking/alerts/",
            data=self._valid_payload(foreign_integration),
            format="json",
        )

        assert response.status_code == 400, response.json()
        assert ErrorTrackingAlert.objects.for_team(self.team.id).count() == 0

    def test_alert_detail_with_malformed_id_returns_404(self):
        retrieve = self.client.get(f"/api/projects/{self.team.id}/error_tracking/alerts/not-a-uuid/")
        assert retrieve.status_code == 404

        delete = self.client.delete(f"/api/projects/{self.team.id}/error_tracking/alerts/not-a-uuid/")
        assert delete.status_code == 404

    def test_alerts_are_isolated_per_team(self):
        other_team = self.create_team_with_organization(organization=self.organization)
        with team_scope(other_team.id):
            foreign_alert = ErrorTrackingAlert.objects.create(
                team=other_team,
                name="Other team alert",
                triggers=["issue_created"],
                channel_type="slack",
                config={"channel": "C0123"},
            )

        listing = self.client.get(f"/api/projects/{self.team.id}/error_tracking/alerts/")
        assert listing.status_code == 200
        assert listing.json()["results"] == []

        retrieve = self.client.get(f"/api/projects/{self.team.id}/error_tracking/alerts/{foreign_alert.id}/")
        assert retrieve.status_code == 404
