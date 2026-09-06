import datetime as dt

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

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

    # --- Lifecycle transitions on update (state machine + audit, not bare field writes) ---

    def _make_firing_alert(self, **overrides):
        base = _payload(state="firing", consecutive_failures=2)
        base.update(overrides)
        return MetricsAlertConfiguration.objects.create(team=self.team, **base)

    def test_disable_transitions_state_and_writes_audit(self):
        alert = self._make_firing_alert()
        response = self.client.patch(self._url(f"{alert.id}/"), {"enabled": False}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.content
        alert.refresh_from_db()
        assert alert.state == "not_firing"
        assert alert.enabled is False
        # disable preserves consecutive_failures (forensics), unlike enable/reset
        assert alert.consecutive_failures == 2
        event = MetricsAlertEvent.objects.get(alert=alert, kind=MetricsAlertEvent.Kind.DISABLE)
        assert event.state_before == "firing"
        assert event.state_after == "not_firing"

    def test_enable_transitions_state_and_reschedules(self):
        alert = self._make_firing_alert(enabled=False, next_check_at=None)
        response = self.client.patch(self._url(f"{alert.id}/"), {"enabled": True}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.content
        alert.refresh_from_db()
        assert alert.state == "not_firing"
        assert alert.consecutive_failures == 0
        # enable clears next_check_at so the scheduler picks the alert up on the next tick
        assert alert.next_check_at is None
        MetricsAlertEvent.objects.get(alert=alert, kind=MetricsAlertEvent.Kind.ENABLE)

    def test_snooze_transitions_state(self):
        alert = self._make_firing_alert(state="not_firing")
        until = (timezone.now() + dt.timedelta(hours=1)).isoformat()
        response = self.client.patch(self._url(f"{alert.id}/"), {"snooze_until": until}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.content
        alert.refresh_from_db()
        assert alert.state == "snoozed"
        assert alert.snooze_until is not None
        MetricsAlertEvent.objects.get(alert=alert, kind=MetricsAlertEvent.Kind.SNOOZE)

    def test_clearing_snooze_unsnoozes(self):
        until = timezone.now() + dt.timedelta(hours=1)
        alert = self._make_firing_alert(state="snoozed", snooze_until=until)
        response = self.client.patch(self._url(f"{alert.id}/"), {"snooze_until": None}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.content
        alert.refresh_from_db()
        assert alert.state == "not_firing"
        assert alert.snooze_until is None
        MetricsAlertEvent.objects.get(alert=alert, kind=MetricsAlertEvent.Kind.UNSNOOZE)

    def test_threshold_change_resets_state_and_reschedules(self):
        alert = self._make_firing_alert()
        response = self.client.patch(self._url(f"{alert.id}/"), {"threshold_value": 250.0}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.content
        alert.refresh_from_db()
        assert alert.state == "not_firing"
        assert alert.consecutive_failures == 0
        assert alert.next_check_at is None
        MetricsAlertEvent.objects.get(alert=alert, kind=MetricsAlertEvent.Kind.THRESHOLD_CHANGE)

    def test_threshold_change_preserves_snooze(self):
        until = timezone.now() + dt.timedelta(hours=1)
        alert = self._make_firing_alert(state="snoozed", snooze_until=until)
        response = self.client.patch(self._url(f"{alert.id}/"), {"threshold_value": 250.0}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.content
        alert.refresh_from_db()
        assert alert.state == "snoozed"

    def test_window_only_change_does_not_touch_state(self):
        alert = self._make_firing_alert()
        response = self.client.patch(self._url(f"{alert.id}/"), {"window_minutes": 15}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.content
        alert.refresh_from_db()
        assert alert.state == "firing"
        assert not MetricsAlertEvent.objects.filter(alert=alert).exists()
