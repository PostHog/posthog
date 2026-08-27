from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.scoping import team_scope

from products.error_tracking.backend.models import ErrorTrackingAlert, ErrorTrackingAlertDestination


class TestErrorTrackingAlerts(APIBaseTest):
    def setUp(self):
        super().setUp()
        flag_patcher = patch("products.error_tracking.backend.logic.alerts.feature_enabled_or_false", return_value=True)
        flag_patcher.start()
        self.addCleanup(flag_patcher.stop)

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
            "destinations": [
                {
                    "channel_type": "slack",
                    "integration_id": integration.id,
                    "config": {"channel": "C0123"},
                }
            ],
        }
        payload.update(overrides)
        return payload

    def _create_alert(self, integration: Integration, **overrides) -> dict:
        response = self.client.post(
            f"/api/projects/{self.team.id}/error_tracking/alerts/",
            data=self._valid_payload(integration, **overrides),
            format="json",
        )
        assert response.status_code == 201, response.json()
        return response.json()

    def test_alert_crud_roundtrip(self):
        integration = self._create_slack_integration()

        created = self._create_alert(integration)
        assert created["name"] == "Notify #alerts"
        assert created["enabled"] is True
        assert created["triggers"] == ["issue_created", "issue_spiking"]
        assert created["throttle_seconds"] == 0
        assert len(created["destinations"]) == 1
        destination = created["destinations"][0]
        assert destination["channel_type"] == "slack"
        assert destination["integration_id"] == integration.id
        assert destination["config"] == {"channel": "C0123"}

        alert_id = created["id"]
        update = self.client.patch(
            f"/api/projects/{self.team.id}/error_tracking/alerts/{alert_id}/",
            data={"enabled": False, "triggers": ["issue_reopened"], "throttle_seconds": 600},
            format="json",
        )
        assert update.status_code == 200, update.json()
        assert update.json()["enabled"] is False
        assert update.json()["triggers"] == ["issue_reopened"]
        assert update.json()["throttle_seconds"] == 600

        listing = self.client.get(f"/api/projects/{self.team.id}/error_tracking/alerts/")
        assert listing.status_code == 200
        assert [alert["id"] for alert in listing.json()["results"]] == [alert_id]

        delete = self.client.delete(f"/api/projects/{self.team.id}/error_tracking/alerts/{alert_id}/")
        assert delete.status_code == 204
        assert self.client.get(f"/api/projects/{self.team.id}/error_tracking/alerts/{alert_id}/").status_code == 404
        assert ErrorTrackingAlertDestination.objects.for_team(self.team.id).count() == 0

    def test_endpoints_require_feature_flag(self):
        integration = self._create_slack_integration()
        with patch("products.error_tracking.backend.logic.alerts.feature_enabled_or_false", return_value=False):
            listing = self.client.get(f"/api/projects/{self.team.id}/error_tracking/alerts/")
            assert listing.status_code == 403
            create = self.client.post(
                f"/api/projects/{self.team.id}/error_tracking/alerts/",
                data=self._valid_payload(integration),
                format="json",
            )
            assert create.status_code == 403
        assert ErrorTrackingAlert.objects.for_team(self.team.id).count() == 0

    def test_alert_create_compiles_filter_bytecode(self):
        integration = self._create_slack_integration()

        created = self._create_alert(
            integration,
            filters={"properties": [{"type": "event", "key": "environment", "value": "production"}]},
        )

        assert created["filters"]["bytecode"] is not None
        stored = ErrorTrackingAlert.objects.for_team(self.team.id).get(id=created["id"])
        assert stored.filters["bytecode"] == created["filters"]["bytecode"]

    def test_alert_update_recompiles_filter_bytecode(self):
        integration = self._create_slack_integration()
        created = self._create_alert(integration)
        assert "properties" not in created["filters"]

        update = self.client.patch(
            f"/api/projects/{self.team.id}/error_tracking/alerts/{created['id']}/",
            data={"filters": {"properties": [{"type": "event", "key": "environment", "value": "production"}]}},
            format="json",
        )

        assert update.status_code == 200, update.json()
        assert update.json()["filters"]["bytecode"] is not None

    def test_alert_create_rejects_uncompilable_filters(self):
        integration = self._create_slack_integration()

        response = self.client.post(
            f"/api/projects/{self.team.id}/error_tracking/alerts/",
            data=self._valid_payload(integration, filters={"properties": [{"type": "hogql", "key": "(select 1)"}]}),
            format="json",
        )

        assert response.status_code == 400, response.json()
        assert ErrorTrackingAlert.objects.for_team(self.team.id).count() == 0

    def test_alert_update_replaces_destinations(self):
        integration = self._create_slack_integration()
        created = self._create_alert(integration)
        old_destination_id = created["destinations"][0]["id"]

        update = self.client.patch(
            f"/api/projects/{self.team.id}/error_tracking/alerts/{created['id']}/",
            data={
                "destinations": [
                    {"channel_type": "slack", "integration_id": integration.id, "config": {"channel": "C0456"}}
                ]
            },
            format="json",
        )

        assert update.status_code == 200, update.json()
        destinations = update.json()["destinations"]
        assert len(destinations) == 1
        assert destinations[0]["config"] == {"channel": "C0456"}
        assert destinations[0]["id"] != old_destination_id
        assert ErrorTrackingAlertDestination.objects.for_team(self.team.id).count() == 1

    @parameterized.expand(
        [
            ("unknown_trigger", {"triggers": ["issue_deleted"]}),
            ("empty_triggers", {"triggers": []}),
            ("empty_destinations", {"destinations": []}),
            ("negative_throttle", {"throttle_seconds": -1}),
            (
                "unknown_channel",
                {"destinations": [{"channel_type": "carrier_pigeon", "integration_id": 1, "config": {}}]},
            ),
            ("missing_integration", {"destinations": [{"channel_type": "slack", "config": {"channel": "C1"}}]}),
            (
                "missing_channel_in_config",
                {"destinations": [{"channel_type": "slack", "integration_id": None, "config": {}}]},
            ),
        ]
    )
    def test_alert_create_rejects_invalid_payload(self, _name, overrides):
        integration = self._create_slack_integration()
        payload = self._valid_payload(integration, **overrides)

        response = self.client.post(
            f"/api/projects/{self.team.id}/error_tracking/alerts/",
            data=payload,
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
            )

        listing = self.client.get(f"/api/projects/{self.team.id}/error_tracking/alerts/")
        assert listing.status_code == 200
        assert listing.json()["results"] == []

        retrieve = self.client.get(f"/api/projects/{self.team.id}/error_tracking/alerts/{foreign_alert.id}/")
        assert retrieve.status_code == 404
