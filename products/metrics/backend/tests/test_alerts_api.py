from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.metrics.backend.models import MetricsAlertConfiguration, MetricsAlertEvent


def _sync_webhook_template() -> None:
    # Destination creation goes through the full HogFunctionSerializer pipeline,
    # which looks up a HogFunctionTemplate by template_id.
    HogFunctionTemplate.objects.get_or_create(
        template_id="template-webhook",
        defaults={
            "sha": "1.0.0",
            "name": "Webhook",
            "description": "Generic webhook template",
            "code": "return event",
            "code_language": "hog",
            "inputs_schema": [{"key": "url", "type": "string"}, {"key": "body", "type": "json"}],
            "type": "destination",
            "status": "stable",
            "category": ["Integrations"],
            "free": True,
        },
    )


def _payload(**overrides):
    base = {
        "name": "High p95 latency",
        "metric_name": "http.server.request.duration",
        "aggregation": "avg",
        "threshold_value": 100.0,
        "threshold_operator": "above",
        "window_minutes": 5,
        "check_interval_minutes": 5,
        "evaluation_periods": 1,
        "datapoints_to_alarm": 1,
    }
    base.update(overrides)
    return base


class TestMetricsAlertsApi(APIBaseTest):
    def setUp(self):
        super().setUp()
        self._flag = patch("posthoganalytics.feature_enabled", return_value=True)
        self._flag.start()
        self.addCleanup(self._flag.stop)
        _sync_webhook_template()

    def _url(self, suffix=""):
        return f"/api/projects/{self.team.id}/metrics/alerts/{suffix}"

    def test_create_alert(self):
        response = self.client.post(self._url(), _payload(), format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.content
        body = response.json()
        assert body["name"] == "High p95 latency"
        assert body["state"] == "not_firing"
        assert body["aggregation"] == "avg"
        assert MetricsAlertConfiguration.objects.filter(team=self.team, name="High p95 latency").exists()

    def test_list_alerts_scoped_to_team(self):
        MetricsAlertConfiguration.objects.create(team=self.team, **_payload())
        other_team = self.organization.teams.create(name="other")
        MetricsAlertConfiguration.objects.create(team=other_team, **_payload(name="other alert"))

        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        names = [r["name"] for r in response.json()["results"]]
        assert "High p95 latency" in names
        assert "other alert" not in names

    def test_quantile_aggregation_requires_quantile(self):
        response = self.client.post(
            self._url(), _payload(aggregation="quantile", quantile=None), format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_datapoints_cannot_exceed_periods(self):
        response = self.client.post(
            self._url(), _payload(evaluation_periods=1, datapoints_to_alarm=3), format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_retrieve_includes_destinations(self):
        alert = MetricsAlertConfiguration.objects.create(team=self.team, **_payload())
        response = self.client.get(self._url(f"{alert.id}/"))
        assert response.status_code == status.HTTP_200_OK
        assert "destinations" in response.json()

    def test_events_endpoint_returns_history(self):
        alert = MetricsAlertConfiguration.objects.create(team=self.team, **_payload())
        MetricsAlertEvent.objects.create(
            alert=alert,
            kind=MetricsAlertEvent.Kind.CHECK,
            value=150.0,
            threshold_breached=True,
            state_before="not_firing",
            state_after="firing",
        )
        response = self.client.get(self._url(f"{alert.id}/events/"))
        assert response.status_code == status.HTTP_200_OK
        events = response.json()
        assert len(events) == 1
        assert events[0]["value"] == 150.0
        assert events[0]["state_after"] == "firing"

    def test_add_webhook_destination(self):
        alert = MetricsAlertConfiguration.objects.create(team=self.team, **_payload())
        response = self.client.post(
            self._url(f"{alert.id}/destinations/"),
            {"type": "webhook", "webhook_url": "https://example.com/hook"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.content
        ids = response.json()["hog_function_ids"]
        # One HogFunction per event kind (firing, resolved, broken, errored).
        assert len(ids) == 4

    def test_delete_destination(self):
        alert = MetricsAlertConfiguration.objects.create(team=self.team, **_payload())
        create = self.client.post(
            self._url(f"{alert.id}/destinations/"),
            {"type": "webhook", "webhook_url": "https://example.com/hook"},
            format="json",
        )
        ids = create.json()["hog_function_ids"]
        response = self.client.post(
            self._url(f"{alert.id}/destinations/delete/"),
            {"hog_function_ids": ids},
            format="json",
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
