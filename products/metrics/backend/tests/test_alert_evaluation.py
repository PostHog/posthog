from datetime import UTC, datetime

from products.metrics.backend.alert_evaluation import _check_result_from_rows, evaluate_metric_alert
from products.metrics.backend.models import MetricsAlertConfiguration


def _alert(**overrides) -> MetricsAlertConfiguration:
    defaults = {
        "metric_name": "http.server.request.duration",
        "aggregation": "avg",
        "threshold_value": 100.0,
        "threshold_operator": "above",
        "window_minutes": 5,
    }
    defaults.update(overrides)
    return MetricsAlertConfiguration(**defaults)


class TestCheckResultFromRows:
    def test_no_rows_is_clear(self):
        alert = _alert()
        result = _check_result_from_rows(alert, [], query_duration_ms=5)
        assert result.threshold_breached is False
        assert result.value is None
        assert result.error_message is None

    def test_above_threshold_breaches(self):
        alert = _alert(threshold_value=100.0, threshold_operator="above")
        rows = [{"time": "2026-09-02T10:00:00", "value": 150.0, "labels": {}}]
        result = _check_result_from_rows(alert, rows, query_duration_ms=5)
        assert result.threshold_breached is True
        assert result.value == 150.0

    def test_above_threshold_below_value_is_clear(self):
        alert = _alert(threshold_value=100.0, threshold_operator="above")
        rows = [{"time": "2026-09-02T10:00:00", "value": 50.0, "labels": {}}]
        result = _check_result_from_rows(alert, rows, query_duration_ms=5)
        assert result.threshold_breached is False
        assert result.value == 50.0

    def test_below_threshold_breaches(self):
        alert = _alert(threshold_value=10.0, threshold_operator="below")
        rows = [{"time": "2026-09-02T10:00:00", "value": 3.0, "labels": {}}]
        result = _check_result_from_rows(alert, rows, query_duration_ms=5)
        assert result.threshold_breached is True
        assert result.value == 3.0

    def test_group_by_breaches_when_any_group_breaches(self):
        alert = _alert(threshold_value=100.0, threshold_operator="above", group_by=[{"key": "service"}])
        rows = [
            {"time": "2026-09-02T10:00:00", "value": 50.0, "labels": {"service": "web"}},
            {"time": "2026-09-02T10:00:00", "value": 250.0, "labels": {"service": "api"}},
        ]
        result = _check_result_from_rows(alert, rows, query_duration_ms=5)
        assert result.threshold_breached is True
        assert result.value == 250.0
        assert result.labels == {"service": "api"}

    def test_group_by_clear_when_no_group_breaches(self):
        alert = _alert(threshold_value=100.0, threshold_operator="above", group_by=[{"key": "service"}])
        rows = [
            {"time": "2026-09-02T10:00:00", "value": 50.0, "labels": {"service": "web"}},
            {"time": "2026-09-02T10:00:00", "value": 60.0, "labels": {"service": "api"}},
        ]
        result = _check_result_from_rows(alert, rows, query_duration_ms=5)
        assert result.threshold_breached is False
        # The reported value is the max (closest to breaching) even when clear.
        assert result.value == 60.0

    def test_uses_latest_bucket_per_group(self):
        alert = _alert(threshold_value=100.0, threshold_operator="above")
        rows = [
            {"time": "2026-09-02T09:55:00", "value": 200.0, "labels": {}},  # older, breached
            {"time": "2026-09-02T10:00:00", "value": 40.0, "labels": {}},  # latest, clear
        ]
        result = _check_result_from_rows(alert, rows, query_duration_ms=5)
        # Latest bucket (40) is below threshold → clear.
        assert result.threshold_breached is False
        assert result.value == 40.0

    def test_skips_none_values(self):
        alert = _alert(threshold_value=100.0, threshold_operator="above")
        rows = [
            {"time": "2026-09-02T10:00:00", "value": None, "labels": {}},
        ]
        result = _check_result_from_rows(alert, rows, query_duration_ms=5)
        assert result.threshold_breached is False
        assert result.value is None


class TestEvaluateMetricAlertWiring:
    def test_window_is_trailing_from_date_to(self):
        """The query window is [date_to - window, date_to)."""
        alert = _alert(window_minutes=5)
        captured = {}

        class FakeRunner:
            def __init__(self, team, metric_name, aggregation, date_from, date_to, filters, group_by, quantile):
                captured["date_from"] = date_from
                captured["date_to"] = date_to

            def run(self):
                return [{"time": "2026-09-02T10:00:00", "value": 1.0, "labels": {}}]

        date_to = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)
        evaluate_metric_alert(alert, team=None, date_to=date_to, query_runner_cls=FakeRunner)  # type: ignore[arg-type]
        assert captured["date_to"] == date_to
        assert (date_to - captured["date_from"]).total_seconds() == 5 * 60
