"""End-to-end activity tests: real metric data → real evaluation → state transition.

The Kafka producer is the only mocked boundary (no broker in tests); we observe the
produced event payloads and the resulting DB state, which is the honest end-to-end
signal: metric rows in ClickHouse drive an alert to FIRING and emit a firing event.
"""

import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.utils import timezone

from posthog.clickhouse.client import sync_execute

from products.metrics.backend.models import MetricsAlertConfiguration, MetricsAlertEvent
from products.metrics.backend.temporal.activities import CheckMetricsAlertInput, _check_metrics_alert_sync, _discover
from products.metrics.backend.tests._seeder import seed_metric


def _alert(team, **overrides):
    base = {
        "team": team,
        "name": "High latency",
        "metric_name": "http.server.request.duration",
        "aggregation": "avg",
        "threshold_value": 100.0,
        "threshold_operator": "above",
        "window_minutes": 5,
        "check_interval_minutes": 5,
        "evaluation_periods": 1,
        "datapoints_to_alarm": 1,
        "enabled": True,
        "next_check_at": timezone.now() - dt.timedelta(minutes=1),  # due now
    }
    base.update(overrides)
    return MetricsAlertConfiguration.objects.create(**base)


def _produce_result_ok():
    result = MagicMock()
    return result


class TestMetricsAlertActivityEndToEnd(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        sync_execute("TRUNCATE TABLE IF EXISTS metrics1")

    def _run_check(self, alert):
        with (
            patch(
                "products.metrics.backend.temporal.activities.produce_alert_internal_event"
            ) as mock_produce,
            patch(
                "products.metrics.backend.temporal.activities.alert_internal_event_delivered",
                return_value=True,
            ),
            patch("products.metrics.backend.temporal.activities.flush_alert_internal_events"),
        ):
            output = _check_metrics_alert_sync(
                CheckMetricsAlertInput(alert_id=str(alert.id), team_id=alert.team_id)
            )
        return output, mock_produce

    def test_breaching_metric_fires_alert(self):
        # Seed a gauge whose latest value (150) breaches the >100 threshold.
        now = timezone.now().replace(microsecond=0)
        seed_metric(
            team_id=self.team.id,
            metric_name="http.server.request.duration",
            metric_type="gauge",
            points=[(now - dt.timedelta(minutes=1), 150.0)],
        )
        alert = _alert(self.team)

        output, mock_produce = self._run_check(alert)

        alert.refresh_from_db()
        assert output.state_before == "not_firing"
        assert output.state_after == "firing"
        assert output.notification == "fire"
        assert alert.state == "firing"

        # A firing event was produced with the evaluated value.
        assert mock_produce.called
        kwargs = mock_produce.call_args.kwargs
        assert kwargs["event_name"] == "$metrics_alert_firing"
        assert kwargs["properties"]["value"] == 150.0
        assert kwargs["properties"]["threshold_value"] == 100.0

        # A CHECK event row recorded the transition.
        event = MetricsAlertEvent.objects.get(alert=alert, kind=MetricsAlertEvent.Kind.CHECK)
        assert event.threshold_breached is True
        assert event.value == 150.0
        assert event.state_after == "firing"

    def test_clear_metric_stays_not_firing(self):
        now = timezone.now().replace(microsecond=0)
        seed_metric(
            team_id=self.team.id,
            metric_name="http.server.request.duration",
            metric_type="gauge",
            points=[(now - dt.timedelta(minutes=1), 40.0)],
        )
        alert = _alert(self.team)

        output, mock_produce = self._run_check(alert)

        alert.refresh_from_db()
        assert output.state_after == "not_firing"
        assert output.notification == "none"
        assert alert.state == "not_firing"
        assert not mock_produce.called

    def test_firing_alert_resolves_when_metric_drops(self):
        now = timezone.now().replace(microsecond=0)
        seed_metric(
            team_id=self.team.id,
            metric_name="http.server.request.duration",
            metric_type="gauge",
            points=[(now - dt.timedelta(minutes=1), 30.0)],
        )
        alert = _alert(self.team, state="firing", last_notified_at=now - dt.timedelta(minutes=5))

        output, mock_produce = self._run_check(alert)

        alert.refresh_from_db()
        assert output.state_after == "not_firing"
        assert output.notification == "resolve"
        kwargs = mock_produce.call_args.kwargs
        assert kwargs["event_name"] == "$metrics_alert_resolved"

    def test_group_by_reports_breaching_labels(self):
        now = timezone.now().replace(microsecond=0)
        seed_metric(
            team_id=self.team.id,
            metric_name="http.server.request.duration",
            metric_type="gauge",
            labels={"service": "api"},
            points=[(now - dt.timedelta(minutes=1), 250.0)],
        )
        seed_metric(
            team_id=self.team.id,
            metric_name="http.server.request.duration",
            metric_type="gauge",
            labels={"service": "web"},
            points=[(now - dt.timedelta(minutes=1), 20.0)],
        )
        alert = _alert(self.team, group_by=[{"key": "service"}])

        output, mock_produce = self._run_check(alert)

        alert.refresh_from_db()
        assert output.state_after == "firing"
        kwargs = mock_produce.call_args.kwargs
        assert kwargs["properties"]["labels"] == {"service": "api"}
        assert kwargs["properties"]["value"] == 250.0

    def test_every_evaluated_check_is_recorded(self):
        # N-of-M reads the window back from CHECK events, so a check must be recorded
        # even when it changes no state — otherwise the first N-1 breaches are lost.
        now = timezone.now().replace(microsecond=0)
        seed_metric(
            team_id=self.team.id,
            metric_name="http.server.request.duration",
            metric_type="gauge",
            points=[(now - dt.timedelta(minutes=1), 40.0)],
        )
        alert = _alert(self.team)

        self._run_check(alert)

        checks = MetricsAlertEvent.objects.filter(alert=alert, kind=MetricsAlertEvent.Kind.CHECK)
        assert checks.count() == 1
        assert checks.get().threshold_breached is False
        assert checks.get().error_message is None

    def test_n_of_m_accumulates_breaches_across_checks(self):
        # 2-of-3: the first breaching check must persist its CHECK row so the second
        # breaching check sees it in get_recent_breaches and fires.
        alert = _alert(self.team, evaluation_periods=3, datapoints_to_alarm=2)

        def seed_breaching_point():
            # Seed near the middle of the 5-minute window, not its edge: the runner
            # evaluates [date_to - window, date_to) where date_to is the (past) scheduled
            # next_check_at, so a point at now-1m can sit seconds inside — or outside —
            # the window depending on wall-clock drift between seed and check.
            now = timezone.now().replace(microsecond=0)
            seed_metric(
                team_id=self.team.id,
                metric_name="http.server.request.duration",
                metric_type="gauge",
                points=[(now - dt.timedelta(minutes=2, seconds=30), 150.0)],
            )

        seed_breaching_point()
        first, _ = self._run_check(alert)
        alert.refresh_from_db()
        assert first.state_after == "not_firing"  # 1 breach < 2 required
        assert alert.state == "not_firing"

        # Mark the alert due again: the first check advanced next_check_at by one
        # interval from its seeded (past) value, which can still sit minutes in the
        # past and push the freshly seeded point out of the next check's window.
        alert.next_check_at = timezone.now() - dt.timedelta(minutes=1)
        alert.save(update_fields=["next_check_at"])

        seed_breaching_point()
        second, mock_produce = self._run_check(alert)
        alert.refresh_from_db()
        assert second.state_after == "firing"
        assert second.notification == "fire"
        assert alert.state == "firing"

    def test_discovery_finds_only_due_enabled_alerts(self):
        _alert(self.team, name="due")
        _alert(self.team, name="not due", next_check_at=timezone.now() + dt.timedelta(hours=1))
        _alert(self.team, name="disabled", enabled=False)
        _alert(self.team, name="new (no schedule)", next_check_at=None)

        with patch("products.metrics.backend.temporal.activities.logger"):
            output = _discover()

        found_names = set()
        for a in output.alerts:
            found_names.add(MetricsAlertConfiguration.objects.get(id=a.alert_id).name)
        assert "due" in found_names
        assert "new (no schedule)" in found_names
        assert "not due" not in found_names
        assert "disabled" not in found_names
